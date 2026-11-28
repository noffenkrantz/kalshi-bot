"""The results page (site/index.html, published to GitHub Pages): the Pinnacle vs Kalshi gap tracker
shown as a real-money account.

    python -m bot gaps --site      rebuild site/index.html and site/gaps.json from data/gap_*.jsonl

The account starts with [gaps] bankroll_usd. Each simulated bet buys up to [gaps] stake_usd of the
cheap side, but only as many contracts as were actually for sale at that price when the bet was
placed (read from Kalshi's order book), and pays Kalshi's fee the way Kalshi charges it (rounded up
to the cent per order). Bets whose order book couldn't be read are left out. Nothing is traded.

The page carries its data inline (so it works anywhere, including as a saved copy) and, when served
from GitHub Pages, also fetches site/gaps.json from the repo so it shows the newest results without
waiting for a redeploy.
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
from datetime import datetime
from pathlib import Path

from .gaps import _mean, _share_edge, _tight, read_jsonl, score_bets, settings
from .strategy import order_fee
from .util import iso, parse_time, utcnow

TEMPLATE = Path(__file__).with_name("gapsite_template.html")


def repo_slug(root: Path) -> str | None:
    for var in ("GITHUB_REPOSITORY", "WATCH_REPO"):
        if os.environ.get(var):
            return os.environ[var]
    try:
        cfg = (Path(root) / ".git" / "config").read_text()
    except OSError:
        return None
    m = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?\s", cfg)
    return m.group(1) if m else None


RECENT = 50            # the quick check reads the latest 50 bets that have a final Pinnacle price
QUICK_TARGET, PROOF_TARGET = 50, 1000


def verdict(scored: list[dict], done: list[dict]) -> dict:
    """The plain read at the top of the page.
    Quick check (closing value): did the bot buy below Pinnacle's last price before each game? It
    settles in about 50 bets. Proof (profit): each bet is close to a coin flip, so a few cents of edge
    only shows in profit after hundreds to about 1,000 settled bets."""
    recent = sorted(scored, key=lambda b: b["ts"])[-RECENT:]
    xs = [b["clv"] for b in recent]
    moves = [b["kalshi_move"] for b in recent if b.get("kalshi_move") is not None]   # Kalshi's price, bet -> game time
    n = len(xs)
    mean = statistics.fmean(xs) if xs else None
    low = (mean - 2 * statistics.stdev(xs) / math.sqrt(n)) if n > 1 else None
    if n < 10:
        state = "early"
    elif mean > 0 and low > 0:
        state = "promising"
    elif mean > 0:
        state = "leaning"
    else:
        state = "not_working"
    m, profit = len(done), round(sum(b["profit"] for b in done), 2)
    if m < 300:
        pstate = "early"
    elif m < PROOF_TARGET:
        pstate = "ahead" if profit > 0 else "behind"
    else:
        pstate = "proven" if profit > 0 else "not_proven"
    return {"state": state, "n": n, "scored_total": len(scored), "mean": mean, "low": low,
            "beat": sum(x > 0 for x in xs), "quick_target": QUICK_TARGET,
            "toward": sum(m >= 0.01 for m in moves), "toward_n": len(moves),
            "profit": profit, "settled": m, "wins": sum(bool(b.get("won", b.get("result") == b.get("side"))) for b in done),
            "profit_state": pstate, "proof_target": PROOF_TARGET}


MODES = [
    {"key": "main", "name": "All bets",
     "about": "Buys whenever Kalshi is cheap enough compared with Pinnacle, and holds every bet until the game ends."},
    {"key": "fav", "name": "Favorites only",
     "about": "The same bets, but only when Pinnacle gives the side the bot backs more than a 50% chance."},
    {"key": "sell", "name": "Sell early",
     "about": "The same bets, but sells before the game if Kalshi will pay the price Pinnacle gave when the bet "
              "was placed (paying Kalshi's fee again on the sale). Bets that never get there are held to the end."},
]


def account(bets: list[dict], settled_at: dict, latest_fair: dict, start: float, now: datetime, first: str,
            sell: bool = False) -> dict:
    """Replay one experiment's bets in time order: what a real account would have done."""
    events = []
    for b in bets:
        events.append((b["ts"], 0, b))
        settled = settled_at.get(b["ticker"]) if b.get("result") else None
        if sell and b.get("exit_ts") and (settled is None or b["exit_ts"] < settled):
            events.append((b["exit_ts"], 1, b))           # sold before the game
        elif settled:
            events.append((settled, 2, b))
    events.sort(key=lambda e: (e[0], e[1]))
    cash, realized = start, 0.0
    held, placed, finished = {}, [], []
    left = {"missed": 0, "unknown": 0, "no_cash": 0, "same_game": 0}
    real_line = [[first, start]]
    for ts, kind, b in events:
        key = (b["ticker"], b["side"])
        if kind == 0:
            if any(h.get("event") == b.get("event") for h in held.values()):   # same game, same bet twice
                left["same_game"] += 1
            elif b.get("available") is None:               # couldn't see what was for sale: left out
                left["unknown"] += 1
            elif b["n"] == 0:
                left["missed"] += 1
            elif b["cost"] > cash:
                left["no_cash"] += 1
            else:
                cash -= b["cost"]
                held[key] = b
                placed.append(b)
        elif key in held:
            held.pop(key)
            if kind == 1:
                cash += b["n"] * b["exit_price"] - order_fee(b["exit_price"], b["n"])
                done = {**b, "profit": b["exit_profit"], "how": "sold", "won": b["exit_profit"] > 0, "closed": ts}
            else:
                cash += b["n"] if b["result"] == b["side"] else 0
                won = b["result"] == b["side"]
                done = {**b, "how": "won" if won else "lost", "won": won, "closed": ts}
            finished.append(done)
            realized += done["profit"]
            real_line.append([ts, round(start + realized, 2)])
    balance = round(start + realized, 2)
    real_line.append([iso(now), balance])

    def fair_now(b):
        f = latest_fair.get(b["ticker"])
        return None if f is None else round(f if b["side"] == "yes" else 1 - f, 4)

    open_rows = []
    for b in sorted(held.values(), key=lambda b: b["starts"]):
        fn = fair_now(b)
        ev = round(b["n"] * (fn if fn is not None else b["fair"]) - b["cost"], 2)
        open_rows.append({"placed": b["ts"], "game": b["pin_teams"], "league": b["league"], "team": b["team"],
                          "side": b["side"], "price": b["price"], "n": b["n"], "wanted": b["contracts"],
                          "available": b["available"], "cost": b["cost"], "fair_then": b["fair"], "fair_now": fn,
                          "ev": ev, "starts": b["starts"], "live": bool(b.get("live"))})
    projected = round(balance + sum(r["ev"] for r in open_rows), 2)
    scored = [b for b in placed if b.get("clv") is not None]
    settled_rows = [{"placed": b["ts"], "settled": b["closed"], "game": b["pin_teams"], "league": b["league"],
                     "team": b["team"], "side": b["side"], "price": b["price"], "n": b["n"], "cost": b["cost"],
                     "how": b["how"], "won": b["won"], "profit": b["profit"], "clv": b.get("clv"),
                     "exit_price": b.get("exit_price") if b["how"] == "sold" else None}
                    for b in sorted(finished, key=lambda b: b["closed"], reverse=True)[:40]]
    return {
        "account": {"start": start, "balance": balance, "realized": round(realized, 2), "cash": round(cash, 2),
                    "projected": projected, "open_n": len(open_rows), "open_cost": round(sum(r["cost"] for r in open_rows), 2),
                    "settled_n": len(finished), "wins": sum(b["won"] for b in finished),
                    "losses": sum(not b["won"] for b in finished), "sold_n": sum(b["how"] == "sold" for b in finished),
                    "placed_n": len(placed), **{f"{k}_n": v for k, v in left.items()},
                    "clv": _mean(b["clv"] for b in scored), "clv_n": len(scored),
                    "clv_usd": round(sum(b["clv"] * b["n"] for b in scored), 2)},
        "real_line": real_line, "proj_line": [real_line[-2], [iso(now), projected]] if open_rows else [],
        "verdict": verdict(scored, finished), "open": open_rows, "settled": settled_rows,
    }


def build_data(root: Path, cfg: dict, now: datetime | None = None) -> dict:
    now = now or utcnow()
    g = settings(cfg)
    data = Path(root) / "data"
    snaps = read_jsonl(data / "gap_snaps.jsonl")
    bets = score_bets(data)
    settled_at = {o["ticker"]: o["ts"] for o in read_jsonl(data / "gap_outcomes.jsonl")}
    latest_fair = {}
    for s in snaps:
        latest_fair[s["ticker"]] = s["fair"]
    try:
        state = json.loads((data / "gap_state.json").read_text())
    except (OSError, ValueError):
        state = {}
    start = float(g["bankroll_usd"])
    first = snaps[0]["ts"] if snaps else (min(b["ts"] for b in bets) if bets else iso(now))
    modes = {}
    for m in MODES:
        subset = [b for b in bets if (b.get("fair") or 0) > 0.5] if m["key"] == "fav" else bets
        modes[m["key"]] = {**m, **account(subset, settled_at, latest_fair, start, now, first, sell=m["key"] == "sell")}
    tight = [s for s in snaps if _tight(s)]
    return {
        "updated": iso(now), "repo": repo_slug(root),
        "rules": {"bankroll": start, "stake": float(g["stake_usd"]), "min_edge": float(g["min_edge"]),
                  "max_edge": float(g["max_edge"]), "mode": g.get("mode", "hourly"), "every": g["every_minutes"],
                  "poll": g.get("poll_seconds", 5)},
        "status": {"last_run": state.get("last_run"), "calls_today": state.get("calls"), "day": state.get("day")},
        **{k: v for k, v in modes["main"].items() if k not in ("key", "name", "about")},   # the main page, as before
        "modes": modes, "mode_order": [m["key"] for m in MODES],
        "scan": {"rows": len(snaps), "since": first if snaps else None, "edge": _share_edge(tight) if tight else None},
    }


def render(data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":"), default=str)
    payload = (payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return TEMPLATE.read_text().replace("/*__DATA__*/null", payload, 1)


def page_version() -> str:
    """A short fingerprint of the page design. A page that finds newer data with a different
    fingerprint reloads itself, so a phone's saved copy of an old design doesn't linger."""
    import hashlib
    return hashlib.sha1(TEMPLATE.read_bytes()).hexdigest()[:10]


def write_site(root: Path, cfg: dict, now: datetime | None = None, page: bool = True) -> dict:
    """site/gaps.json always; site/index.html too unless page=False (a new page means a Pages deploy)."""
    data = {**build_data(root, cfg, now), "page": page_version()}
    out = Path(root) / "site"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gaps.json").write_text(json.dumps(data, separators=(",", ":"), default=str) + "\n")
    if page:
        (out / "index.html").write_text(render(data))
    return data
