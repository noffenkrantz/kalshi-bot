"""Phone-friendly dashboard, written to README.md so it's the repo's front page.

Rebuilt after every run. Shows the practice (fake-money) account first, then
paper trades at real prices, then whether Claude is beating the market.
"""
from __future__ import annotations

import os
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from . import lessons as lessons_mod
from .journal import Journal
from .learning import focus_label, topic_stats, topic_weights
from .kalshi import KalshiClient, KalshiError
from .report import MIN_RESOLVED_FOR_VERDICT, _brier
from .strategy import quotes
from .chart import write_balance_charts
from .util import iso, parse_time, to_float, valid_price

SPARK = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float]) -> str:
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return SPARK[3] * len(values)
    return "".join(SPARK[int((v - lo) / (hi - lo) * (len(SPARK) - 1))] for v in values)


def money(x: float, sign: bool = False) -> str:
    body = f"${abs(x):,.2f}"
    if sign:
        return ("+" if x >= 0 else "−") + body
    return ("−" if x < 0 else "") + body


def cents(p: float | None) -> str:
    return "–" if p is None else f"{p * 100:.0f}¢"


def short(text: str | None, n: int = 42) -> str:
    text = (text or "").replace("|", "/").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def when(dt: datetime | None, tz: ZoneInfo) -> str:
    if not dt:
        return ""
    d = dt.astimezone(tz)
    return f"{d:%a %b} {d.day}, {d.strftime('%I').lstrip('0')}:{d:%M} {d:%p} {d.tzname() or ''}".strip()


def _book(rows: list[dict], journal: Journal, env: str) -> tuple[list[dict], list[dict]]:
    """Group trades by market and side; split into open and settled."""
    book: dict = {}
    for r in rows:
        key = (r["ticker"], r["outcome"])
        p = book.setdefault(key, {"ticker": r["ticker"], "outcome": r["outcome"], "contracts": 0.0,
                                  "cost": 0.0, "paid": 0.0, "ts": r.get("ts"), "row_question": r.get("question")})
        p["contracts"] += r["contracts"]
        p["cost"] += r["cost"]                       # includes fees
        p["paid"] += r["contracts"] * (r.get("price") or 0.0)  # price only
    open_, settled = [], []
    for p in book.values():
        est = journal.latest_estimate(p["ticker"]) or {}
        p["question"] = est.get("question") or p.get("row_question") or p["ticker"]
        p["claude"] = est.get("prob_yes")
        p["avg_price"] = p["paid"] / p["contracts"] if p["contracts"] else 0.0
        result = journal.outcome(env, p["ticker"])
        if result:
            p["won"] = result == p["outcome"]
            p["pnl"] = (p["contracts"] if p["won"] else 0.0) - p["cost"]
            settled.append(p)
        else:
            open_.append(p)
    return open_, settled


def _mark(open_: list[dict], client: KalshiClient | None) -> None:
    """Look up today's price for each open position."""
    for p in open_[:30]:
        p["now"] = None
        if client is None:
            continue
        try:
            m = client.get_market(p["ticker"])
        except KalshiError:
            continue
        mid = quotes(m).mid
        if mid is None:
            mid = to_float(m.get("last_price_dollars"))
        if valid_price(mid):
            p["now"] = mid if p["outcome"] == "yes" else 1 - mid
    for p in open_:
        p.setdefault("now", None)
        p["value"] = p["contracts"] * p["now"] if p["now"] is not None else None
        p["pnl"] = (p["value"] - p["cost"]) if p["value"] is not None else None


def _trade_tables(open_: list[dict], settled: list[dict]) -> list[str]:
    out = []
    if open_:
        out += ["", "**Open trades**", "", "| Market | Bet | Cost | Now | P&L |", "|---|---|---|---|---|"]
        for p in sorted(open_, key=lambda x: x.get("ts") or "", reverse=True):
            bet = f"{p['contracts']:g} {p['outcome'].upper()} @ {cents(p['avg_price'])}"
            pnl = money(p["pnl"], sign=True) if p["pnl"] is not None else "–"
            out.append(f"| {short(p['question'])} | {bet} | {money(p['cost'])} | {cents(p['now'])} | {pnl} |")
    if settled:
        out += ["", "**Settled trades**", "", "| Market | Bet | Result | P&L |", "|---|---|---|---|"]
        for p in sorted(settled, key=lambda x: x.get("ts") or "", reverse=True)[:15]:
            bet = f"{p['contracts']:g} {p['outcome'].upper()} @ {cents(p['avg_price'])}"
            result = "✅ won" if p["won"] else "❌ lost"
            out.append(f"| {short(p['question'])} | {bet} | {result} | {money(p['pnl'], sign=True)} |")
    return out


def _summary_line(open_: list[dict], settled: list[dict]) -> str:
    wins = sum(1 for p in settled if p["won"])
    settled_pnl = sum(p["pnl"] for p in settled)
    in_play = sum(p["cost"] for p in open_)
    parts = [f"{len(open_)} open trade{'s' if len(open_) != 1 else ''} ({money(in_play)} in)"]
    if settled:
        parts.append(f"{len(settled)} settled: {wins} won, {len(settled) - wins} lost, "
                     f"{money(settled_pnl, sign=True)}")
    else:
        parts.append("none settled yet")
    return " · ".join(parts)


def build_dashboard(journal: Journal, clients: dict[str, KalshiClient], now: datetime, cfg: dict,
                    record: bool = False) -> str:
    """record=True also saves today's simulated account value, so the trend line grows each run."""
    tz = ZoneInfo(cfg.get("dashboard", {}).get("timezone", "America/New_York"))
    repo = None
    if os.environ.get("GITHUB_REPOSITORY"):
        repo = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}"
    links = [f"[▶ Run now]({repo}/actions/workflows/bot.yml)"] if repo else []
    if repo and repo.startswith("https://github.com/"):
        owner, name = os.environ["GITHUB_REPOSITORY"].split("/", 1)
        links.append(f"[Results site](https://{owner.lower()}.github.io/{name}/)")   # GitHub Pages, see pages.yml
    links += ["[Full report](REPORT.md)", "[Where prices lag](LAGS.md)", "[Last run log](data/last_run.log)", "[Setup & settings](SETUP.md)"]

    out = ["# Kalshi bot", "",
           f"**Updated {when(now, tz)}** · runs every 4 hours · " + " · ".join(links), ""]
    halted = journal.state.get("halted:shadow")
    if halted:
        out += [f"> ⚠️ **Paused by a safety check:** {halted.get('reason')}", ""]

    # ---- simulated account: real markets and prices, fake money ---------------------
    bankroll = float(cfg.get("shadow", {}).get("paper_bankroll", 1000))
    out.append("## 💵 Simulated account")
    out += ["", "*Real Kalshi markets at real prices, with Kalshi's fees, settled on what actually happened. "
                "The money is pretend: nothing is ever bought.*"]
    rows = [{"ticker": d["ticker"], "outcome": d["outcome"], "contracts": d.get("count") or 0,
             "cost": d.get("est_cost") or 0.0, "price": d.get("outcome_price"), "ts": d.get("ts"),
             "question": d.get("question")}
            for d in journal.rows["decisions"]
            if d.get("env") == "shadow" and d.get("action", "").startswith("paper_buy")]
    open_, settled = _book(rows, journal, "shadow")
    _mark(open_, clients.get("shadow"))
    value = bankroll + sum(p["pnl"] for p in settled) + sum(p["pnl"] or 0 for p in open_)
    if record:   # one point per run, so the chart grows every 4 hours
        journal.append("equity", {"ts": iso(now), "env": "shadow", "equity": round(value, 2)})
    history = [(parse_time(r["ts"]), r["equity"]) for r in journal.rows["equity"]
               if r.get("env") == "shadow" and parse_time(r.get("ts"))]
    if record:
        write_balance_charts(history, bankroll, journal.dir, tz)
    out += ["", f"### {money(value)}",
            f"{money(value - bankroll, sign=True)} since the start ({money(bankroll)} pretend bankroll)"]
    if (journal.dir / "balance-light.svg").exists():
        alt = f"Chart of the simulated balance over time, now {money(value)}"
        out += ["", "<picture>",
                '  <source media="(prefers-color-scheme: dark)" srcset="data/balance-dark.svg">',
                f'  <img alt="{alt}" src="data/balance-light.svg" width="100%">',
                "</picture>"]
    if not rows:
        out += ["", "No trades yet. They appear when Claude finds a real market it thinks is mispriced "
                    "by enough to beat the fees.", ""]
    else:
        out += ["", _summary_line(open_, settled) + " · open trades valued at today's prices"]
        out += _trade_tables(open_, settled)
        out.append("")

    # ---- scorecard ------------------------------------------------------------------
    out.append("## 🎯 Is Claude beating the market?")
    resolved = []
    for e in journal.rows["estimates"]:
        if e.get("env") != "shadow" or e.get("market_mid") is None:
            continue
        result = journal.outcome("shadow", e["ticker"])
        if result:
            resolved.append((e["prob_yes"], e["market_mid"], 1.0 if result == "yes" else 0.0))
    total = sum(1 for e in journal.rows["estimates"] if e.get("env") == "shadow")
    if not resolved:
        out += ["", f"{total} forecasts made on real markets, none resolved yet. "
                    "Check back once some markets close.", ""]
    else:
        cb = _brier([(p, y) for p, _, y in resolved])
        mb = _brier([(m, y) for _, m, y in resolved])
        ahead = "**Claude is ahead**" if cb < mb else "**The market is ahead**"
        early = (f" Too early to trust: {len(resolved)}/{MIN_RESOLVED_FOR_VERDICT} resolved."
                 if len(resolved) < MIN_RESOLVED_FOR_VERDICT else "")
        out += ["", f"{ahead}: accuracy score {cb:.3f} for Claude vs {mb:.3f} for the market price "
                    f"(lower is better) on {len(resolved)} resolved forecast{'s' if len(resolved) != 1 else ''}.{early}", ""]

    # ---- learning -------------------------------------------------------------------
    stats = topic_stats(journal, "shadow")
    weights = topic_weights(stats)
    reviews = [p for p in journal.rows["postmortems"] if p.get("env") == "shadow"]
    lessons = lessons_mod.load(journal.dir / "lessons.md")
    explore = float(cfg.get("learning", {}).get("explore_share", 0.2))
    out.append("## 🧠 What Claude is learning")
    if not stats and not reviews and not lessons:
        out += ["", "Nothing has settled yet. Once bets settle, this shows which topics Claude is good at, "
                    "where it's focusing its research, and lessons it has learned from its mistakes.", ""]
    else:
        if stats:
            out += ["", "**Where Claude is good** (settled forecasts where Claude and the market disagreed "
                        "by 5+ points)", "", "| Topic | Claude beat the market | Research focus |", "|---|---|---|"]
            for topic, st in sorted(stats.items(), key=lambda kv: -kv[1]["n"]):
                beat = f"{st['wins']} of {st['disagreements']}" if st["disagreements"] else "no disagreements yet"
                out.append(f"| {short(topic, 28)} | {beat} | {focus_label(topic, weights)} |")
            out += ["", f"*{explore:.0%} of research is always spread at random, so every topic keeps "
                        "getting chances.*"]
        if reviews:
            c = Counter(p.get("verdict") for p in reviews)
            out += ["", f"**Post-mortems:** {len(reviews)} settled bet{'s' if len(reviews) != 1 else ''} reviewed: "
                        f"{c['good_call']} good call{'s' if c['good_call'] != 1 else ''}, {c['bad_luck']} bad luck, "
                        f"{c['process_mistake']} process mistake{'s' if c['process_mistake'] != 1 else ''}"
                        + (f", {c['unclear']} unclear" if c["unclear"] else "") + "."]
            icon = {"good_call": "✅", "bad_luck": "🎲", "process_mistake": "🔧", "unclear": "❔"}
            for p in reversed(reviews[-3:]):
                q = (journal.latest_estimate(p["ticker"]) or {}).get("question") or p["ticker"]
                out.append(f"- {icon.get(p.get('verdict'), '•')} {short(q, 40)}: {short(p.get('what_happened'), 110)}")
        out += ["", f"**Lessons learned ({len(lessons)})** · [see all or edit](data/lessons.md)"]
        if lessons:
            out += [f"- [{l['topic']}] {l['text']}" for l in reversed(lessons[-5:])]
        else:
            out.append("- None yet. Only process mistakes become lessons, never bad luck.")
        out.append("")

    # ---- latest forecasts -----------------------------------------------------------
    recent = journal.rows["estimates"][-10:]
    if recent:
        out += ["## 🔮 Latest forecasts", "", "| Market | Claude | Market | Sure? |", "|---|---|---|---|"]
        for r in reversed(recent):
            mid = r.get("market_mid")
            out.append(f"| {short(r.get('question') or r.get('ticker'))} | {r.get('prob_yes', 0):.0%} | "
                       f"{'–' if mid is None else f'{mid:.0%}'} | {r.get('confidence', '')} |")
        out.append("")

    out += ["---", "*Simulated trades only, no real money. Not financial advice.*", ""]
    return "\n".join(out)
