"""Offline tests for the live gap tracker: a fake clock, fake pinnapi and fake Kalshi."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from bot.gaps import PinnError, write_report
from bot.gaps_live import LiveGaps

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
START = NOW + timedelta(hours=5)
CFG = {"gaps": {"sports": ["soccer"], "poll_seconds": 5, "kalshi_sweep_seconds": 30}}
EV = "KXEFLL2GAME-26NOV25BROGIL"


class Clock:
    def __init__(self):
        self.t = NOW

    def __call__(self):
        return self.t


def pin_event(home_odds=2.0, off=False):
    ml = None if off else {"home": home_odds, "draw": 3.5, "away": 3.6}
    return {"event_id": 10, "league_name": "England - League Two", "home": "Bromley", "away": "Gillingham",
            "starts": START.isoformat(), "parent_id": None, "periods": {"num_0": {"money_line": ml}}}


class FakePinn:
    def __init__(self):
        self.calls, self.changes, self.fail = 0, [], None

    def prematch(self, sport_id):
        self.calls += 1
        return {"last": 100, "events": [pin_event()] if sport_id == 1 else []}

    def get(self, path, params):
        self.calls += 1
        if self.fail:
            raise PinnError(self.fail)
        assert path == "/kit/v1/markets" and params["since"] is not None
        out, self.changes = self.changes, []
        return {"last": params["since"] + 1, "events": out}


class FakeKalshi:
    def __init__(self):
        self.q = {f"{EV}-BRO": (0.44, 0.46), f"{EV}-GIL": (0.25, 0.28), f"{EV}-TIE": (0.24, 0.27)}
        self.names = {f"{EV}-BRO": "Bromley", f"{EV}-GIL": "Gillingham", f"{EV}-TIE": "Tie"}
        self.requests = []

    def market(self, t):
        b, a = self.q[t]
        return {"ticker": t, "event_ticker": EV, "yes_sub_title": self.names[t], "yes_bid_dollars": f"{b:.4f}",
                "yes_ask_dollars": f"{a:.4f}", "volume_24h_fp": "50.00"}

    def iter_markets(self, max_markets=1000, **p):
        if p["series_ticker"] == "KXEFLL2GAME":
            yield from (self.market(t) for t in self.q)

    def request(self, method, path, params=None):
        self.requests.append(params)
        if params and "event_ticker" in params:
            return {"markets": [self.market(t) for t in self.q]}
        if params and "tickers" in params:
            return {"markets": [self.market(t) for t in params["tickers"].split(",")]}
        return {"market": {"result": getattr(self, "results", {}).get(path.split("/")[-1], "")}}


def setup(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "niche_survey.json").write_text(json.dumps({"series": [{"series": "KXEFLL2GAME", "category": "Sports"}]}))
    clock, kalshi, pinn, lines = Clock(), FakeKalshi(), FakePinn(), []
    return LiveGaps(tmp_path, CFG, kalshi, pinn, clock=clock, say=lines.append), clock, kalshi, pinn, lines


def rows(tmp_path, name):
    p = tmp_path / "data" / name
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_a_pinnacle_move_is_bet_at_once_and_followed_up(tmp_path):
    live, clock, kalshi, pinn, lines = setup(tmp_path)
    live.tick()                                            # pair the games; Kalshi agrees with Pinnacle: no bet
    assert len(live.links) == 1 and rows(tmp_path, "gap_bets.jsonl") == []
    pinn.changes = [pin_event(home_odds=1.70)]             # Bromley shortens: fair 0.47 -> 0.51
    clock.t += timedelta(seconds=5)
    live.tick()
    (bet,) = rows(tmp_path, "gap_bets.jsonl")
    assert bet["side"] == "yes" and bet["team"] == "Bromley" and bet["price"] == 0.46 and bet["live"]
    assert bet["ts"] == (NOW + timedelta(seconds=5)).isoformat()
    assert rows(tmp_path, "gap_snaps.jsonl")[-1]["ts"] == bet["ts"]          # entry price kept for scoring
    assert live.new_bets == 1 and live.dirty

    kalshi.q[f"{EV}-BRO"] = (0.54, 0.56)                   # Kalshi catches up within 15 seconds
    for s in (15, 60, 300):
        clock.t = NOW + timedelta(seconds=5 + s)
        live.tick()
    (move,) = rows(tmp_path, "gap_moves.jsonl")
    assert move["ticker"] == f"{EV}-BRO" and move["mid_before"] == 0.45 and move["mid_at"] == 0.45
    assert move["after"]["15"]["mid"] == 0.55 and move["fair_after"] > 0.50
    text = write_report(tmp_path)
    assert "How fast Kalshi follows Pinnacle" in text and "| England - League Two | 1 |" in text


def test_no_bets_while_pinnacle_has_the_game_off_the_board(tmp_path):
    live, clock, kalshi, pinn, _ = setup(tmp_path)
    live.tick()
    pinn.changes = [pin_event(off=True)]                   # news: Pinnacle pulls the game
    clock.t += timedelta(seconds=5)
    live.tick()
    kalshi.q[f"{EV}-GIL"] = (0.10, 0.12)                   # Kalshi drops Gillingham hard
    clock.t += timedelta(seconds=30)
    live.tick()
    assert rows(tmp_path, "gap_bets.jsonl") == [] and live.pin[10] is None
    assert any(p and "tickers" in p for p in kalshi.requests)          # the sweep did read Kalshi


def test_kalshi_drift_on_its_own_is_caught_by_the_sweep(tmp_path):
    live, clock, kalshi, pinn, _ = setup(tmp_path)
    live.tick()
    kalshi.q[f"{EV}-GIL"] = (0.18, 0.21)                   # fair 0.27: 4.8c edge after fees
    clock.t += timedelta(seconds=31)
    live.tick()
    (bet,) = rows(tmp_path, "gap_bets.jsonl")
    assert bet["team"] == "Gillingham" and bet["price"] == 0.21


def test_daily_limit_pauses_for_an_hour(tmp_path):
    live, clock, kalshi, pinn, lines = setup(tmp_path)
    live.tick()
    pinn.fail = 'GET /kit/v1/markets: rate limited twice: {"error":"rate_limited","window":"day","limit":100}'
    clock.t += timedelta(seconds=5)
    live.tick()
    assert live.next["poll"] == clock.t + timedelta(hours=1) and any("paid plan" in x for x in lines)


def test_one_bet_per_game_the_best_side(tmp_path):
    live, clock, kalshi, pinn, _ = setup(tmp_path)
    kalshi.q[f"{EV}-BRO"] = (0.38, 0.40)                   # YES Bromley: fair 0.47, ~5.3c edge
    kalshi.q[f"{EV}-GIL"] = (0.33, 0.35)                   # NO Gillingham at 0.67 vs fair 0.73: ~4.5c edge
    live.tick()
    (bet,) = rows(tmp_path, "gap_bets.jsonl")
    assert bet["team"] == "Bromley" and bet["side"] == "yes"
    kalshi.q[f"{EV}-TIE"] = (0.15, 0.17)                   # a new edge on the same game later: still no second bet
    clock.t += timedelta(seconds=31)
    live.tick()
    assert len(rows(tmp_path, "gap_bets.jsonl")) == 1


def test_results_are_picked_up_soon_after_the_game_and_published_at_once(tmp_path):
    live, clock, kalshi, pinn, _ = setup(tmp_path)
    kalshi.q[f"{EV}-BRO"] = (0.38, 0.40)
    live.tick()                                            # bets Bromley; the game starts in 5 hours
    live.dirty, live.new_bets = False, 0
    kalshi.results = {f"{EV}-BRO": "yes"}
    clock.t = START + timedelta(minutes=70)                # too soon to check
    live.tick()
    assert rows(tmp_path, "gap_outcomes.jsonl") == []
    clock.t = START + timedelta(minutes=80)
    live.tick()
    assert [o["result"] for o in rows(tmp_path, "gap_outcomes.jsonl")] == ["yes"]
    assert live.new_results == 1 and live.dirty and (tmp_path / "site" / "gaps.json").exists()
