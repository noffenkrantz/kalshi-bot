"""Builds site/index.html: a self-contained results page (data embedded) that is published
to GitHub Pages (.github/workflows/pages.yml) and as a private Claude artifact.
Rebuilt after every run by `python -m bot report`."""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import lessons as lessons_mod
from .dashboard import _book, _mark, balance_lines
from .journal import Journal
from .kalshi import KalshiClient
from .lags import summarize as lag_summary
from .learning import focus_label, topic_for, topic_stats, topic_weights
from .util import iso

TEMPLATE = Path(__file__).with_name("site_template.html")
def build_site_data(journal: Journal, clients: dict[str, KalshiClient], now: datetime, cfg: dict) -> dict:
    start = float(cfg.get("shadow", {}).get("paper_bankroll", 10000))
    rows = [{"ticker": d["ticker"], "outcome": d["outcome"], "contracts": d.get("count") or 0,
             "cost": d.get("est_cost") or 0.0, "price": d.get("outcome_price"), "ts": d.get("ts"),
             "question": d.get("question")}
            for d in journal.rows["decisions"]
            if d.get("env") == "shadow" and d.get("action", "").startswith("paper_buy")]
    open_, settled = _book(rows, journal, "shadow")
    _mark(open_, clients.get("shadow"))
    balance, projected, real_line, proj_line = balance_lines(journal, open_, settled, start, now)

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
            out.update(now=p.get("now"), proj=None if p.get("proj") is None else round(p["proj"], 2))
        return out


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
        "updated": iso(now), "repo": os.environ.get("GITHUB_REPOSITORY"), "start": start, "balance": balance,
        "projected": projected,
        "real_line": [[iso(t), v] for t, v in real_line][-400:],
        "proj_line": [[iso(t), round(v, 2)] for t, v in proj_line][-400:],
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
        "lags": lag_data(journal),
    }


def lag_data(journal: Journal) -> dict:
    """Compact lag-scanner summary for the page (full tables are in LAGS.md)."""
    s = lag_summary(journal.rows["lag_scan"], top=5)
    repo = os.environ.get("GITHUB_REPOSITORY")
    def m(x):
        return None if x is None else round(x, 4)
    return {
        "markets": s["markets"], "jumps": s["jumps"],
        "url": f"https://github.com/{repo}/blob/main/LAGS.md" if repo else None,
        "cats": [{"name": c["name"], "markets": c["markets"], "jumps": c["jumps"], "d30": m(c["d30"]["mean"]),
                  "follow": m(c["follow"]["mean"]), "verdict": c["verdict"]} for c in s["categories"]],
        "top": [{"name": x["name"], "category": x["category"], "jumps": x["jumps"], "d30": m(x["d30"]["mean"]),
                 "follow": m(x["follow"]["mean"]), "verdict": x["verdict"]} for x in s["series_top"]],
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
