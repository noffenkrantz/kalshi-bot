"""Builds site/index.html: a self-contained results page (data embedded) that is published
to GitHub Pages (.github/workflows/pages.yml) and as a private Claude artifact.
Rebuilt after every run by `python -m bot report`."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import lessons as lessons_mod
from .dashboard import _book, _mark
from .journal import Journal
from .kalshi import KalshiClient
from .learning import focus_label, topic_for, topic_stats, topic_weights
from .util import iso, parse_time

TEMPLATE = Path(__file__).with_name("site_template.html")
RUN_GAP = timedelta(minutes=210)   # matches MIN_GAP_MINUTES in .github/workflows/bot.yml
CHECK_MINUTE = 41                   # the workflow checks hourly at :41 past (cron "41 * * * *")


def next_run(now: datetime) -> datetime:
    """First hourly check at least RUN_GAP after this run, i.e. when the next run is due.
    GitHub can still start it a little late."""
    earliest = (now + RUN_GAP).astimezone(timezone.utc)
    t = earliest.replace(minute=CHECK_MINUTE, second=0, microsecond=0)
    return t if t >= earliest else t + timedelta(hours=1)


def build_site_data(journal: Journal, clients: dict[str, KalshiClient], now: datetime, cfg: dict) -> dict:
    start = float(cfg.get("shadow", {}).get("paper_bankroll", 10000))
    rows = [{"ticker": d["ticker"], "outcome": d["outcome"], "contracts": d.get("count") or 0,
             "cost": d.get("est_cost") or 0.0, "price": d.get("outcome_price"), "ts": d.get("ts"),
             "question": d.get("question")}
            for d in journal.rows["decisions"]
            if d.get("env") == "shadow" and d.get("action", "").startswith("paper_buy")]
    open_, settled = _book(rows, journal, "shadow")
    _mark(open_, clients.get("shadow"))
    balance = start + sum(p["pnl"] for p in settled) + sum(p["pnl"] or 0 for p in open_)

    reviews = {p["ticker"]: p for p in journal.rows["postmortems"] if p.get("env") == "shadow"}
    first_dec = {}
    for d in journal.rows["decisions"]:
        if d.get("env") == "shadow" and d.get("action", "").startswith("paper_buy"):
            first_dec.setdefault(d["ticker"], d)

    def bet_row(p: dict) -> dict:
        d = first_dec.get(p["ticker"], {})
        est = journal.latest_estimate(p["ticker"]) or {}
        out = {"q": p["question"], "side": p["outcome"], "contracts": p["contracts"], "price": p["avg_price"],
               "cost": round(p["cost"], 2), "claude": d.get("prob_yes", p.get("claude")),
               "market": d.get("market_mid"), "placed": p.get("ts"), "closes": d.get("close_time") or est.get("close_time"),
               "topic": topic_for(est or d, journal), "src": d.get("source") or "research"}
        if out["src"] == "watcher":
            out["why"] = d.get("reason")
        if "won" in p:
            r = reviews.get(p["ticker"], {})
            out.update(won=p["won"], pnl=round(p["pnl"], 2), verdict=r.get("verdict"), note=r.get("what_happened"))
        else:
            out.update(now=p.get("now"), pnl=None if p.get("pnl") is None else round(p["pnl"], 2))
        return out

    history = [[r["ts"], r["equity"]] for r in journal.rows["equity"]
               if r.get("env") == "shadow" and parse_time(r.get("ts"))]
    if not history or history[-1][1] != round(balance, 2):
        history.append([iso(now), round(balance, 2)])

    resolved = []
    for e in journal.rows["estimates"]:
        if e.get("env") == "shadow" and e.get("market_mid") is not None and journal.outcome("shadow", e["ticker"]):
            y = 1.0 if journal.outcome("shadow", e["ticker"]) == "yes" else 0.0
            resolved.append((e["prob_yes"], e["market_mid"], y))
    bet_tickers = set(first_dec)
    forecasts = []
    for e in reversed(journal.rows["estimates"]):
        if e.get("env") != "shadow" or e.get("market_mid") is None:
            continue
        forecasts.append({"q": e.get("question") or e["ticker"], "claude": e.get("prob_yes"), "market": e["market_mid"],
                          "conf": e.get("confidence"), "ts": e.get("ts"), "topic": topic_for(e, journal),
                          "bet": e["ticker"] in bet_tickers, "result": journal.outcome("shadow", e["ticker"])})
        if len(forecasts) >= 12:
            break

    stats = topic_stats(journal, "shadow")
    weights = topic_weights(stats)
    today = now.strftime("%Y-%m-%d")
    wins = sum(1 for p in settled if p["won"])
    return {
        "updated": iso(now), "next_run": iso(next_run(now)), "start": start, "balance": round(balance, 2),
        "history": history[-400:],
        "open": [bet_row(p) for p in sorted(open_, key=lambda x: x.get("ts") or "", reverse=True)],
        "settled": [bet_row(p) for p in sorted(settled, key=lambda x: x.get("ts") or "", reverse=True)][:40],
        "stats": {"open_n": len(open_), "open_cost": round(sum(p["cost"] for p in open_), 2),
                  "settled_n": len(settled), "wins": wins, "losses": len(settled) - wins,
                  "settled_pnl": round(sum(p["pnl"] for p in settled), 2),
                  "forecasts_n": sum(1 for e in journal.rows["estimates"] if e.get("env") == "shadow"),
                  "resolved_n": len(resolved),
                  "claude_brier": round(sum((p - y) ** 2 for p, _, y in resolved) / len(resolved), 4) if resolved else None,
                  "market_brier": round(sum((m - y) ** 2 for _, m, y in resolved) / len(resolved), 4) if resolved else None},
        "forecasts": forecasts,
        "topics": [{"topic": t, "n": s["n"], "dis": s["disagreements"], "wins": s["wins"],
                    "focus": focus_label(t, weights)} for t, s in sorted(stats.items(), key=lambda kv: -kv[1]["n"])],
        "reviews": dict(Counter(p.get("verdict") for p in journal.rows["postmortems"] if p.get("env") == "shadow")),
        "lessons": [{"topic": l["topic"], "text": l["text"], "count": l["count"]}
                    for l in reversed(lessons_mod.load(journal.dir / "lessons.md"))],
        "rules": {"bet": cfg["strategy"].get("bet_size_dollars", 100), "conf": cfg["strategy"].get("min_confidence"),
                  "edge": cfg["strategy"].get("min_edge"), "budget": cfg["claude"].get("daily_budget_usd")},
        "spend_today": round(journal.claude_spend_on(today, "shadow"), 2),
    }


def render_site(data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":"), default=str)
    # safe inside <script>: no "</script>", no HTML parsing surprises
    payload = (payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return TEMPLATE.read_text().replace("/*__DATA__*/null", payload, 1)


def write_site(journal: Journal, clients: dict[str, KalshiClient], now: datetime, cfg: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_site(build_site_data(journal, clients, now, cfg)))
    return out
