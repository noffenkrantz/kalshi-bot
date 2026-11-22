"""Offline tests: a full bot cycle against a fake Kalshi and a fake Claude.

Run with:  python -m pytest -q
No network, no keys, no money.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from bot.config import load_config
from bot.journal import Journal
from bot.kalshi import KalshiClient, KalshiError, sign
from bot.report import build_report
from bot.runner import Bot, run_once
from bot.strategy import Account, decide, order_fee

NOW = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parent.parent


def market(ticker, yes_bid, yes_ask, volume=1000, close_hours=48, event="EV1"):
    return {
        "ticker": ticker, "event_ticker": event, "market_type": "binary",
        "yes_sub_title": f"{ticker} happens", "rules_primary": f"Resolves YES if {ticker} happens.",
        "close_time": (NOW + timedelta(hours=close_hours)).isoformat().replace("+00:00", "Z"),
        "yes_bid_dollars": f"{yes_bid:.4f}", "yes_ask_dollars": f"{yes_ask:.4f}",
        "no_bid_dollars": f"{1 - yes_ask:.4f}", "no_ask_dollars": f"{1 - yes_bid:.4f}",
        "yes_bid_size_fp": "500.00", "yes_ask_size_fp": "500.00",
        "volume_24h_fp": f"{volume:.2f}", "result": "",
    }


class FakeKalshi:
    def __init__(self, env, markets, authed=True, flip_direction=False, cash=1000.0):
        self.env = env
        self.markets = {m["ticker"]: m for m in markets}
        self.authenticated = authed
        self.orders, self.positions = {}, []
        self.flip_direction = flip_direction
        self.cash = cash

    def exchange_status(self):
        return {"trading_active": True}

    def iter_markets(self, max_markets=5000, **params):
        assert params.get("status") == "open" and params.get("mve_filter") == "exclude"
        yield from list(self.markets.values())[:max_markets]

    def get_market(self, ticker):
        return self.markets[ticker]

    def get_event(self, event_ticker):
        return {"title": f"Event {event_ticker}", "category": "Sports" if event_ticker == "SPORT" else "Economics"}

    def get_balance(self):
        return {"balance": int(self.cash * 100), "balance_dollars": f"{self.cash:.4f}", "portfolio_value": 0}

    def get_positions(self):
        return self.positions

    def create_order(self, ticker, book_side, count, price, client_order_id=None, time_in_force="immediate_or_cancel"):
        assert book_side in ("bid", "ask") and isinstance(price, str)
        oid = f"o{len(self.orders) + 1}"
        outcome = "yes" if book_side == "bid" else "no"
        if self.flip_direction:
            outcome = "no" if outcome == "yes" else "yes"
        self.orders[oid] = {"order_id": oid, "ticker": ticker, "book_side": book_side, "price": price,
                            "count": count, "outcome_side": outcome, "status": "executed"}
        cost_each = float(price) if book_side == "bid" else 1 - float(price)
        self.cash -= count * cost_each
        self.positions.append({"ticker": ticker, "position_fp": f"{count if outcome == 'yes' else -count:.2f}",
                               "market_exposure_dollars": f"{count * cost_each:.4f}"})
        return {"order_id": oid, "client_order_id": client_order_id or "cid", "fill_count": f"{count:.2f}",
                "remaining_count": "0.00", "average_fee_paid": "0.0175", "ts_ms": 1}

    def get_order(self, order_id):
        return self.orders[order_id]


class FakeClaude:
    """Research call -> pauses once, then returns notes. Judge call -> JSON."""

    def __init__(self, probs: dict, confidence="high"):
        self.probs = probs
        self.confidence = confidence
        self.calls = []
        self.paused = set()

    postmortem_replies: dict = {}   # ticker -> dict reply for post-mortem reviews

    def create(self, body):
        self.calls.append(body)
        if body.get("system", "").startswith("You review one settled"):
            brief = body["messages"][0]["content"]
            ticker = brief.split("Ticker: ")[1].split()[0]
            reply = self.postmortem_replies.get(ticker, {"verdict": "bad_luck", "what_happened": "x",
                                                         "mistake": "", "lesson": "", "applies_to": "this topic",
                                                         "reinforces": 0})
            return {"stop_reason": "end_turn", "usage": {"input_tokens": 2000, "output_tokens": 200},
                    "content": [{"type": "text", "text": "Review notes.\n" + json.dumps(reply)}]}
        text = body["messages"][0]["content"]
        self.lessons_seen = getattr(self, "lessons_seen", {})
        ticker = text.split("Market ticker: ")[1].split("\n")[0]
        if "tools" in body:
            assert body["tools"][0]["type"] == "web_search_20250305"
            self.lessons_seen[ticker] = "Lessons from reviewing" in text
            if ticker not in self.paused:
                self.paused.add(ticker)
                return {"stop_reason": "pause_turn", "usage": {"input_tokens": 1000, "output_tokens": 100},
                        "content": [{"type": "server_tool_use", "id": "s1", "name": "web_search",
                                     "input": {"query": ticker}}]}
            assert body["messages"][-1]["role"] == "assistant"  # paused turn sent back
            return {"stop_reason": "end_turn",
                    "usage": {"input_tokens": 8000, "output_tokens": 600, "server_tool_use": {"web_search_requests": 2}},
                    "content": [{"type": "web_search_tool_result", "tool_use_id": "s1",
                                 "content": [{"type": "web_search_result", "url": f"https://example.gov/{ticker}"}]},
                                {"type": "text", "text": f"Research on {ticker}. Probability about {self.probs[ticker]}.",
                                 "citations": [{"url": f"https://example.gov/{ticker}"}]}]}
        assert body["output_config"]["format"]["type"] == "json_schema"
        payload = {"probability_yes": self.probs[ticker], "confidence": self.confidence.upper(),
                   "rules_clear": True, "resolution_summary": "x", "key_evidence": ["e"],
                   "would_change_my_mind": "y", "red_flags": []}
        return {"stop_reason": "end_turn", "usage": {"input_tokens": 3000, "output_tokens": 200},
                "content": [{"type": "text", "text": json.dumps(payload)}]}

    def cost_usd(self, usage, model):
        usage = usage or {}
        searches = (usage.get("server_tool_use") or {}).get("web_search_requests", 0)
        return usage.get("input_tokens", 0) * 2 / 1e6 + usage.get("output_tokens", 0) * 10 / 1e6 + searches * 0.01


@pytest.fixture
def cfg():
    return load_config(ROOT / "config.toml")


def make_bot(tmp_path, cfg, mode, kalshi, claude, now=NOW):
    return Bot(mode=mode, cfg=cfg, data=kalshi, trade=None if mode == "shadow" else kalshi,
               claude=claude, journal=Journal(tmp_path / "data"), now=now, root=tmp_path)


MARKETS = [
    market("UNDER", 0.40, 0.42, volume=5000, event="EV1"),   # Claude says 70% -> buy YES
    market("OVER", 0.60, 0.62, volume=4000, event="EV2"),    # Claude says 30% -> buy NO
    market("FAIR", 0.49, 0.51, volume=3000, event="EV3"),    # Claude says 50% -> skip
    market("SPORTY", 0.30, 0.32, volume=9000, event="SPORT"),  # excluded category
    market("WIDE", 0.20, 0.50, volume=9000),    # spread too wide
    market("SOON", 0.40, 0.42, volume=9000, close_hours=2),  # closes too soon
]
PROBS = {"UNDER": 0.70, "OVER": 0.30, "FAIR": 0.50}


# ---- signing ----------------------------------------------------------------------
def test_signature_verifies_with_kalshi_scheme():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sig = sign(key, "1700000000000", "get", "/trade-api/v2/portfolio/balance")
    key.public_key().verify(
        base64.b64decode(sig), b"1700000000000GET/trade-api/v2/portfolio/balance",
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256())


def test_client_signs_full_path_without_query_and_builds_v2_order():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    seen = []

    class Resp:
        status_code, content = 201, b"{}"
        text = "{}"

        def json(self):
            return {"order_id": "abc", "fill_count": "1.00"}

    class Session:
        def request(self, method, url, params=None, json=None, headers=None, timeout=None):
            seen.append((method, url, params, json, headers))
            return Resp()

    c = KalshiClient("demo", key_id="kid", private_key=key, session=Session(), min_interval=0)
    c.create_order("TICK", "ask", 3, "0.4000")
    method, url, params, body, headers = seen[0]
    assert url == "https://external-api.demo.kalshi.co/trade-api/v2/portfolio/events/orders"
    assert body["side"] == "ask" and body["count"] == "3" and body["price"] == "0.4000"
    assert body["time_in_force"] == "immediate_or_cancel"
    assert body["self_trade_prevention_type"] == "taker_at_cross"
    ts = headers["KALSHI-ACCESS-TIMESTAMP"]
    key.public_key().verify(
        base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]),
        (ts + "POST/trade-api/v2/portfolio/events/orders").encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256())
    with pytest.raises(KalshiError):
        KalshiClient("demo").get_balance()  # no key -> refuses


# ---- strategy -------------------------------------------------------------------------
def test_fee_matches_kalshi_formula():
    assert order_fee(0.50, 100) == 1.75
    assert order_fee(0.50, 1) == 0.02     # 0.0175 rounds up to the next cent
    assert order_fee(0.90, 10) == 0.07    # 0.063 -> 0.07


def test_decide_buy_yes_buy_no_and_skip(cfg):
    acct = Account(bankroll=1000)
    s, r = cfg["strategy"], cfg["risk"]
    d = decide(MARKETS[0], {"prob_yes": 0.70, "confidence": "high", "rules_clear": True}, s, r, acct)
    assert d.action == "buy_yes" and d.book_side == "bid" and d.api_price == "0.4200"
    assert 95 <= d.est_cost <= 101                          # flat ~$100 bet
    d = decide(MARKETS[1], {"prob_yes": 0.30, "confidence": "high", "rules_clear": True}, s, r, acct)
    # buy NO at 0.40 == sell YES at the YES bid of 0.60
    assert d.action == "buy_no" and d.book_side == "ask" and d.api_price == "0.6000"
    assert abs(d.outcome_price - 0.40) < 1e-9
    assert decide(MARKETS[2], {"prob_yes": 0.50, "confidence": "high", "rules_clear": True}, s, r, acct).action == "skip"
    assert decide(MARKETS[0], {"prob_yes": 0.70, "confidence": "medium", "rules_clear": True}, s, r, acct).action == "skip"
    assert decide(MARKETS[0], {"prob_yes": 0.70, "confidence": "medium-high", "rules_clear": True}, s, r, acct).action == "buy_yes"
    assert decide(MARKETS[0], {"prob_yes": 0.70, "confidence": "Medium High", "rules_clear": True}, s, r, acct).action == "buy_yes"
    assert decide(MARKETS[0], {"prob_yes": 0.70, "confidence": "medium-low", "rules_clear": True}, s, r, acct).action == "skip"
    assert decide(MARKETS[0], {"prob_yes": 0.70, "confidence": "low", "rules_clear": True}, s, r, acct).action == "skip"
    small_edge = decide(MARKETS[0], {"prob_yes": 0.48, "confidence": "high", "rules_clear": True}, s, r, acct)
    assert small_edge.action == "skip" and "below" in small_edge.reason   # 6 cents < 8 cent minimum
    thin = dict(MARKETS[0], yes_ask_size_fp="40.00")                       # only ~$17 for sale
    assert "minimum bet" in decide(thin, {"prob_yes": 0.70, "confidence": "high", "rules_clear": True}, s, r, acct).reason
    assert decide(MARKETS[0], {"prob_yes": 0.70, "confidence": "high", "rules_clear": False}, s, r, acct).action == "skip"
    full = Account(bankroll=1000, exposure=r["max_total_exposure"])
    assert decide(MARKETS[0], {"prob_yes": 0.70, "confidence": "high", "rules_clear": True}, s, r, full).action == "skip"


# ---- full runs ------------------------------------------------------------------------
def test_shadow_run_paper_trades_and_respects_filters(tmp_path, cfg):
    k, c = FakeKalshi("prod", MARKETS, authed=False), FakeClaude(PROBS)
    bot = make_bot(tmp_path, cfg, "shadow", k, c)
    run_once(bot)
    j = bot.journal
    tickers = {e["ticker"] for e in j.rows["estimates"]}
    assert tickers == {"UNDER", "OVER", "FAIR"}            # filters removed the other three
    paper = [d for d in j.rows["decisions"] if d["action"].startswith("paper_buy")]
    assert {(d["ticker"], d["outcome"]) for d in paper} == {("UNDER", "yes"), ("OVER", "no")}
    assert not k.orders                                     # shadow never trades
    assert j.rows["estimates"][0]["sources"] == ["https://example.gov/UNDER"]
    calls = len(c.calls)
    run_once(make_bot(tmp_path, cfg, "shadow", k, c, now=NOW + timedelta(hours=1)))
    assert len(c.calls) == calls                            # fresh forecasts reused, no new Claude spend


def test_demo_run_places_correct_orders_and_limits(tmp_path, cfg):
    k, c = FakeKalshi("demo", MARKETS), FakeClaude(PROBS)
    bot = make_bot(tmp_path, cfg, "demo", k, c)
    run_once(bot)
    placed = {(o["ticker"], o["book_side"], o["price"]) for o in k.orders.values()}
    assert placed == {("UNDER", "bid", "0.4200"), ("OVER", "ask", "0.6000")}
    rows = bot.journal.rows["orders"]
    assert all(r["status"] == "executed" and r.get("verified") for r in rows)
    # second run: already holding both, so no new orders
    run_once(make_bot(tmp_path, cfg, "demo", k, c, now=NOW + timedelta(hours=1)))
    assert len(k.orders) == 2


def test_max_trades_per_run(tmp_path, cfg):
    cfg["risk"]["max_trades_per_run"] = 1
    k = FakeKalshi("demo", MARKETS)
    run_once(make_bot(tmp_path, cfg, "demo", k, FakeClaude(PROBS)))
    assert len(k.orders) == 1


def test_direction_mismatch_halts(tmp_path, cfg):
    k = FakeKalshi("demo", MARKETS, flip_direction=True)
    bot = make_bot(tmp_path, cfg, "demo", k, FakeClaude(PROBS))
    run_once(bot)
    assert len(k.orders) == 1                               # stopped right after the first bad order
    assert "halted:demo" in bot.journal.state
    bot2 = make_bot(tmp_path, cfg, "demo", k, FakeClaude(PROBS))
    run_once(bot2)
    assert len(k.orders) == 1 and "Not running" in bot2.summary.lines[0]


def test_daily_claude_budget_stops_research(tmp_path, cfg):
    cfg["claude"]["daily_budget_usd"] = 0.001
    c = FakeClaude(PROBS)
    bot = make_bot(tmp_path, cfg, "shadow", FakeKalshi("prod", MARKETS, authed=False), c)
    run_once(bot)
    assert len(bot.journal.rows["estimates"]) == 1          # one analysis, then budget exhausted


def test_drawdown_halts(tmp_path, cfg):
    k = FakeKalshi("demo", MARKETS, cash=1000)
    j = Journal(tmp_path / "data")
    j.set_state("peak_equity:demo", 2000.0)
    bot = make_bot(tmp_path, cfg, "demo", k, FakeClaude(PROBS))
    run_once(bot)
    assert not k.orders and "halted:demo" in bot.journal.state


def test_stop_file_and_live_lock(tmp_path, cfg, monkeypatch):
    (tmp_path / "STOP").write_text("")
    bot = make_bot(tmp_path, cfg, "demo", FakeKalshi("demo", MARKETS), FakeClaude(PROBS))
    run_once(bot)
    assert "STOP" in bot.summary.lines[0]
    (tmp_path / "STOP").unlink()
    monkeypatch.delenv("ALLOW_REAL_MONEY", raising=False)
    k = FakeKalshi("prod", MARKETS)
    bot = make_bot(tmp_path, cfg, "live", k, FakeClaude(PROBS))
    run_once(bot)
    assert not k.orders and "locked" in bot.summary.lines[0]


def test_report_scores_resolved_forecasts(tmp_path, cfg):
    k = FakeKalshi("prod", MARKETS, authed=False)
    run_once(make_bot(tmp_path, cfg, "shadow", k, FakeClaude(PROBS)))
    k.markets["UNDER"]["result"] = "yes"
    k.markets["OVER"]["result"] = "no"
    k.markets["FAIR"]["result"] = "yes"
    j = Journal(tmp_path / "data")
    text = build_report(j, {"shadow": k}, NOW + timedelta(days=3))
    assert "3 resolved" in text
    assert "Claude is BETTER than the market" in text
    assert "Paper trades" in text and "2 won" in text
    assert "Not enough data yet: 3/100" in text


# ---- subscription mode (Claude Code writes the forecasts) -----------------------------
def test_subscription_prepare_ingest_then_trade(tmp_path, cfg):
    from bot.research_queue import ingest, prepare, safe_name
    prod = FakeKalshi("prod", MARKETS, authed=False)
    demo = FakeKalshi("demo", [market("DEMO1", 0.40, 0.42)])
    journal = Journal(tmp_path / "data")
    work = tmp_path / "work"
    queue = prepare(cfg, {"shadow": prod, "demo": demo}, journal, NOW, work)
    assert [q["ticker"] for q in queue] == ["DEMO1", "UNDER", "OVER"]   # 1 demo slot, then shadow up to 3
    text = (work / "INSTRUCTIONS.md").read_text()
    assert "work/queue.json" in text and "probability_yes" in text and "{" not in text.split("## The JSON file")[0]
    # pretend to be Claude Code: write one good file, one broken file, skip one
    (work / "estimates" / safe_name("UNDER")).write_text(json.dumps({
        "probability_yes": 0.7, "confidence": "High", "rules_clear": True, "resolution_summary": "s",
        "key_evidence": ["e"], "would_change_my_mind": "w", "red_flags": [], "sources": ["https://x.gov"]}))
    (work / "estimates" / safe_name("OVER")).write_text("not json")
    added, problems = ingest(journal, work, NOW)
    assert added == 1 and len(problems) == 2
    assert not (work / "queue.json").exists()                          # not ingested twice
    # the run uses the ingested forecast with no API key at all
    bot = Bot(mode="shadow", cfg=cfg, data=prod, trade=None, claude=None, journal=journal, now=NOW, root=tmp_path)
    run_once(bot)
    paper = [d for d in journal.rows["decisions"] if d["action"].startswith("paper_buy")]
    assert [(d["ticker"], d["outcome"]) for d in paper] == [("UNDER", "yes")]
    # next prepare skips the fresh forecast and respects the daily cap
    cfg["subscription"]["max_forecasts_per_day"] = 1
    assert prepare(cfg, {"shadow": prod}, journal, NOW, work) == []


# ---- dashboard ---------------------------------------------------------------------
def test_dashboard_shows_simulated_account(tmp_path, cfg):
    from bot.dashboard import build_dashboard
    prod = FakeKalshi("prod", MARKETS, authed=False)
    j = Journal(tmp_path / "data")
    empty = build_dashboard(j, {"shadow": prod}, NOW, cfg, record=True)
    assert "### $10,000.00" in empty and "No trades yet" in empty and "Practice" not in empty
    assert "<picture>" in empty and len(j.rows["equity"]) == 1   # chart appears even before any bets
    run_once(Bot(mode="shadow", cfg=cfg, data=prod, trade=None, claude=FakeClaude(PROBS), journal=j, now=NOW, root=tmp_path))
    prod.markets["UNDER"]["yes_bid_dollars"], prod.markets["UNDER"]["yes_ask_dollars"] = "0.5000", "0.5200"
    j.append("outcomes", {"env": "shadow", "ticker": "OVER", "result": "no"})
    text = build_dashboard(j, {"shadow": prod}, NOW + timedelta(hours=4), cfg, record=True)
    assert "## 💵 Simulated account" in text and "Open trades" in text and "Settled trades" in text
    assert "228 YES @ 42¢" in text and "51¢" in text           # bought at 42, now worth the 51 mid
    assert "✅ won" in text and "Practice" not in text
    assert j.rows["equity"][-1]["env"] == "shadow"            # balance history recorded every run
    text2 = build_dashboard(j, {"shadow": prod}, NOW + timedelta(hours=8), cfg, record=True)
    assert "<picture>" in text2 and "data/balance-dark.svg" in text2
    light = (tmp_path / "data" / "balance-light.svg").read_text()
    assert light.startswith("<svg") and "<path" in light and "Start $10,000" in light


def test_one_market_per_event(tmp_path, cfg):
    same_event = [market("RAIN-NYC", 0.40, 0.42, volume=5000, event="RAIN"),
                  market("RAIN-BOS", 0.40, 0.42, volume=4000, event="RAIN"),
                  market("CPI", 0.40, 0.42, volume=3000, event="CPI")]
    c = FakeClaude({"RAIN-NYC": 0.7, "RAIN-BOS": 0.7, "CPI": 0.7})
    j = Journal(tmp_path / "data")
    k = FakeKalshi("prod", same_event, authed=False)
    run_once(Bot(mode="shadow", cfg=cfg, data=k, trade=None, claude=c, journal=j, now=NOW, root=tmp_path))
    assert {e["ticker"] for e in j.rows["estimates"]} == {"RAIN-NYC", "CPI"}     # only one per event researched
    # even with a fresh forecast for the second city, no second trade on the same event
    j.append("estimates", {"ts": "2026-11-20T18:00:00+00:00", "env": "shadow", "ticker": "RAIN-BOS",
                           "event_ticker": "RAIN", "prob_yes": 0.7, "confidence": "high", "rules_clear": True,
                           "market_mid": 0.41})
    cfg["filters"]["max_markets_per_event"] = 5
    run_once(Bot(mode="shadow", cfg=cfg, data=k, trade=None, claude=c, journal=j, now=NOW + timedelta(hours=1), root=tmp_path))
    paper = [d["ticker"] for d in j.rows["decisions"] if d["action"].startswith("paper_buy")]
    assert sorted(paper) == ["CPI", "RAIN-NYC"]



# ---- self-improvement ----------------------------------------------------------------
def test_topic_stats_and_budget_allocation(tmp_path):
    import random
    from bot import learning
    j = Journal(tmp_path / "data")
    for i in range(10):   # Weather: Claude right 8/10 when disagreeing; Politics: 2/10
        for topic, right in (("Weather", i < 8), ("Politics", i < 2)):
            t = f"{topic}-{i}"
            j.append("estimates", {"env": "shadow", "ticker": t, "category": topic, "prob_yes": 0.8, "market_mid": 0.5})
            j.append("outcomes", {"env": "shadow", "ticker": t, "result": "yes" if right else "no"})
    stats = learning.topic_stats(j)
    assert stats["Weather"]["wins"] == 8 and stats["Politics"]["wins"] == 2 and stats["Weather"]["disagreements"] == 10
    weights = learning.topic_weights(stats)
    assert learning.focus_label("Weather", weights) == "⬆ more"
    assert learning.focus_label("Politics", weights) == "⬇ less"
    assert learning.focus_label("Brand new topic", weights) == "normal"
    pool = [{"topic": t, "m": {"ticker": f"{t}{i}"}} for t in ("Weather", "Politics", "New") for i in range(200)]
    focus = learning.allocate(pool, 300, weights, 0.0, random.Random(1))
    n = {t: sum(1 for x in focus if x["topic"] == t) for t in ("Weather", "Politics", "New")}
    assert n["Weather"] > n["New"] > n["Politics"] > 0          # follows results, but nobody is cut off
    explore = learning.allocate(pool, 300, weights, 1.0, random.Random(1))
    assert all(x["picked_by"] == "explore" for x in explore)
    assert sum(1 for x in explore if x["topic"] == "Politics") > 60   # exploration spreads evenly


def test_lessons_file(tmp_path):
    from bot import lessons
    path = tmp_path / "lessons.md"
    assert lessons.add_or_reinforce(path, "Weather", "Check whether a trace counts as zero.", 0, "2026-11-23") == "added"
    assert lessons.add_or_reinforce(path, "All", "Prefer the resolution source over news.", 0, "2026-11-24") == "added"
    assert lessons.add_or_reinforce(path, "All", "prefer the resolution source over news.", 0, "2026-11-25") == "skipped"
    assert lessons.add_or_reinforce(path, "", "", 1, "2026-11-25") == "reinforced"
    loaded = lessons.load(path)
    assert loaded[0]["count"] == 2 and loaded[1]["topic"] == "All"
    assert [l["text"] for l in lessons.relevant(loaded, "weather")] == [l["text"] for l in loaded]
    assert len(lessons.relevant(loaded, "Economics")) == 1
    # you can delete a lesson from your phone by removing its line
    path.write_text("\n".join(l for l in path.read_text().splitlines() if "trace" not in l))
    assert [l["topic"] for l in lessons.load(path)] == ["All"]
    for i in range(40):
        lessons.add_or_reinforce(path, "X", f"lesson {i}", 0, "2026-12-01", max_lessons=30)
    assert len(lessons.load(path)) == 30
    holdout = [t for t in (f"T{i}" for i in range(500)) if not lessons.uses_lessons(t, 0.2)]
    assert 60 < len(holdout) < 140 and lessons.uses_lessons(holdout[0], 0.2) is False


def test_postmortems_turn_only_process_mistakes_into_lessons(tmp_path, cfg):
    prod = FakeKalshi("prod", MARKETS, authed=False)
    c = FakeClaude(PROBS)
    j = Journal(tmp_path / "data")
    run_once(Bot(mode="shadow", cfg=cfg, data=prod, trade=None, claude=c, journal=j, now=NOW, root=tmp_path))
    assert {d["ticker"] for d in j.rows["decisions"] if d["action"].startswith("paper_buy")} == {"UNDER", "OVER"}
    est = j.latest_estimate("UNDER")
    assert est["category"] == "Economics" and est["picked_by"] in ("focus", "explore") and "notes" in est
    # both markets close and settle; UNDER (bought YES) loses, OVER (bought NO) wins
    later = NOW + timedelta(days=3)
    prod.markets["UNDER"]["result"], prod.markets["OVER"]["result"] = "no", "no"
    c.postmortem_replies = {
        "UNDER": {"verdict": "process_mistake", "what_happened": "Used a two-day-old forecast.",
                  "mistake": "stale source", "lesson": "Use the latest official release, not older articles.",
                  "applies_to": "this topic", "reinforces": 0},
        "OVER": {"verdict": "bad_luck", "what_happened": "Fine.", "mistake": "",
                 "lesson": "This should be ignored because it's bad luck.", "applies_to": "all topics", "reinforces": 0},
    }
    bot = Bot(mode="shadow", cfg=cfg, data=prod, trade=None, claude=c, journal=j, now=later, root=tmp_path)
    run_once(bot)
    reviews = {p["ticker"]: p for p in j.rows["postmortems"]}
    assert reviews["UNDER"]["verdict"] == "process_mistake" and reviews["UNDER"]["lesson_action"] == "added"
    assert reviews["OVER"]["verdict"] == "bad_luck" and reviews["OVER"]["lesson"] == ""
    from bot import lessons
    saved = lessons.load(tmp_path / "data" / "lessons.md")
    assert [(l["topic"], l["text"]) for l in saved] == [("Economics", "Use the latest official release, not older articles.")]
    assert any("Post-mortem UNDER: process mistake" in line for line in bot.summary.lines)
    # reviewed once only
    run_once(Bot(mode="shadow", cfg=cfg, data=prod, trade=None, claude=c, journal=j, now=later + timedelta(hours=4), root=tmp_path))
    assert len(j.rows["postmortems"]) == 2
    # lessons reach new research, except for the control group
    from bot.dashboard import build_dashboard
    text = build_dashboard(j, {"shadow": prod}, later, cfg)
    assert "What Claude is learning" in text and "Use the latest official release" in text and "1 process mistake" in text


def test_lessons_reach_research_except_control_group(tmp_path, cfg):
    from bot import lessons
    ticker_with = next(t for t in (f"MKT{i}" for i in range(100)) if lessons.uses_lessons(t, 0.2))
    ticker_without = next(t for t in (f"MKT{i}" for i in range(100)) if not lessons.uses_lessons(t, 0.2))
    mk = [market(ticker_with, 0.40, 0.42, event="E1"), market(ticker_without, 0.40, 0.42, event="E2")]
    (tmp_path / "data").mkdir()
    lessons.add_or_reinforce(tmp_path / "data" / "lessons.md", "Economics", "Check the release calendar.", 0, "2026-11-20")
    c = FakeClaude({ticker_with: 0.7, ticker_without: 0.7})
    j = Journal(tmp_path / "data")
    run_once(Bot(mode="shadow", cfg=cfg, data=FakeKalshi("prod", mk, authed=False), trade=None, claude=c,
                 journal=j, now=NOW, root=tmp_path))
    assert c.lessons_seen == {ticker_with: True, ticker_without: False}
    assert j.latest_estimate(ticker_with)["used_lessons"] is True
    assert j.latest_estimate(ticker_without)["used_lessons"] is False


def test_report_breakdowns(tmp_path, cfg):
    prod = FakeKalshi("prod", MARKETS, authed=False)
    j = Journal(tmp_path / "data")
    run_once(Bot(mode="shadow", cfg=cfg, data=prod, trade=None, claude=FakeClaude(PROBS), journal=j, now=NOW, root=tmp_path))
    for t in ("UNDER", "OVER", "FAIR"):
        prod.markets[t]["result"] = "yes"
    text = build_report(j, {"shadow": prod}, NOW + timedelta(days=3))
    assert "By topic" in text and "Economics" in text and "By Claude's confidence" in text
    assert "By distance from the market price" in text and "Do the lessons help?" in text


def test_no_research_on_events_already_bet(tmp_path, cfg):
    mk = [market("RAIN-NYC", 0.40, 0.42, volume=5000, event="RAIN"),
          market("CPI", 0.40, 0.42, volume=3000, event="CPI")]
    k = FakeKalshi("prod", mk, authed=False)
    c = FakeClaude({"RAIN-NYC": 0.7, "CPI": 0.7, "RAIN-BOS": 0.7})
    j = Journal(tmp_path / "data")
    run_once(Bot(mode="shadow", cfg=cfg, data=k, trade=None, claude=c, journal=j, now=NOW, root=tmp_path))
    assert {d["ticker"] for d in j.rows["decisions"] if d["action"].startswith("paper_buy")} == {"RAIN-NYC", "CPI"}
    k.markets["RAIN-BOS"] = market("RAIN-BOS", 0.40, 0.42, volume=9000, event="RAIN")
    before = len(c.calls)
    run_once(Bot(mode="shadow", cfg=cfg, data=k, trade=None, claude=c, journal=j, now=NOW + timedelta(hours=1), root=tmp_path))
    assert len(c.calls) == before          # RAIN-BOS skipped: already betting on the RAIN event


def test_confidence_scale_normalizing():
    from bot.strategy import normalize_confidence
    assert normalize_confidence("Medium_High") == "medium-high"
    assert normalize_confidence(" medium-low ") == "medium-low"
    assert normalize_confidence("HIGH") == "high"
    assert normalize_confidence("very sure") == "low" and normalize_confidence(None) == "low"


def test_balance_chart_svg():
    from xml.etree import ElementTree
    from zoneinfo import ZoneInfo
    from bot.chart import balance_svg
    pts = [(NOW + timedelta(hours=4 * i), 10000 + 100 * ((-1) ** i) * i) for i in range(20)]
    for theme in ("light", "dark"):
        svg = balance_svg(pts, 10000, theme, ZoneInfo("America/New_York"))
        root = ElementTree.fromstring(svg)                  # well-formed XML
        assert root.tag.endswith("svg") and "Nov 21" in svg and "Start $10,000" in svg
    assert "grows with each run" in balance_svg(pts[:1], 10000)


def test_results_site_builds_and_is_injection_safe(tmp_path, cfg):
    import re
    from bot.site import build_site_data, render_site, next_run
    prod = FakeKalshi("prod", MARKETS, authed=False)
    j = Journal(tmp_path / "data")
    run_once(Bot(mode="shadow", cfg=cfg, data=prod, trade=None, claude=FakeClaude(PROBS), journal=j, now=NOW, root=tmp_path))
    j.rows["estimates"][0]["question"] = "Evil </script><img src=x onerror=alert(1)> market & co"
    data = build_site_data(j, {"shadow": prod}, NOW + timedelta(hours=1), cfg)
    assert data["stats"]["open_n"] == 2 and data["balance"] > 0 and len(data["forecasts"]) == 3
    html = render_site(data)
    assert html.startswith("<!DOCTYPE html>") and "/*__DATA__*/" not in html
    script = html.split("const D = ", 1)[1]
    assert html.count("</script>") == 2                         # only the page's own two script tags
    blob = script.split(";\nconst $ =", 1)[0]
    assert json.loads(blob)["forecasts"][-1]["q"].startswith("Evil </script>")  # round-trips intact
    assert next_run(NOW).strftime("%H:%M") == "20:17"           # NOW is 18:00 UTC
