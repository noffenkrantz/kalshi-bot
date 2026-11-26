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
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .gaps import _mean, _mid, _share_edge, _tight, move_stats, read_jsonl, score_bets, settings
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

    # ---- the account, replayed in time order -------------------------------------------------
    start = float(g["bankroll_usd"])
    events = []
    for b in bets:
        events.append((b["ts"], 0, b))
        if b.get("result") and b["ticker"] in settled_at:
            events.append((settled_at[b["ticker"]], 1, b))
    events.sort(key=lambda e: (e[0], e[1]))
    first = snaps[0]["ts"] if snaps else (events[0][0] if events else iso(now))
    cash, realized = start, 0.0
    held, placed, missed, unknown, no_cash, same_game = {}, [], [], [], [], []
    real_line = [[first, start]]
    for ts, kind, b in events:
        key = (b["ticker"], b["side"])
        if kind == 0:
            if any(h.get("event") == b.get("event") for h in held.values()):   # same game, same bet twice
                same_game.append(b)
            elif b.get("available") is None:               # couldn't see what was for sale: left out
                unknown.append(b)
            elif b["n"] == 0:
                missed.append(b)
            elif b["cost"] > cash:
                no_cash.append(b)
            else:
                cash -= b["cost"]
                held[key] = b
                placed.append(b)
        elif key in held:
            held.pop(key)
            cash += b["n"] if b["result"] == b["side"] else 0
            realized += b["profit"]
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
                          "ev": ev, "starts": b["starts"], "live": bool(b.get("live")),
                          "exit_price": b.get("exit_price"), "exit_profit": b.get("exit_profit"), "exit_ts": b.get("exit_ts")})
    projected = round(balance + sum(r["ev"] for r in open_rows), 2)
    proj_line = [real_line[-2], [iso(now), projected]] if open_rows else []   # dashed: from the last settlement to now
    done = [b for b in placed if b.get("profit") is not None and (b["ticker"], b["side"]) not in held]
    scored = [b for b in placed if b.get("clv") is not None]
    settled_rows = [{"placed": b["ts"], "settled": settled_at.get(b["ticker"]), "game": b["pin_teams"],
                     "league": b["league"], "team": b["team"], "side": b["side"], "price": b["price"], "n": b["n"],
                     "cost": b["cost"], "won": b["result"] == b["side"], "profit": b["profit"], "clv": b.get("clv"),
                     "exit_price": b.get("exit_price"), "exit_profit": b.get("exit_profit")}
                    for b in sorted(done, key=lambda b: settled_at.get(b["ticker"], ""), reverse=True)[:40]]
    missed_rows = [{"placed": b["ts"], "game": b["pin_teams"], "league": b["league"], "team": b["team"],
                    "side": b["side"], "price": b["price"], "edge": b["edge"]}
                   for b in sorted(missed, key=lambda b: b["ts"], reverse=True)[:10]]

    # ---- where the gaps are ------------------------------------------------------------------
    tight = [s for s in snaps if _tight(s)]
    per = defaultdict(list)
    for s in snaps:
        per[s["league"]].append(s)
    bets_by_league = defaultdict(list)
    for b in placed:
        bets_by_league[b["league"]].append(b)
    leagues = []
    for lg, rows in sorted(per.items(), key=lambda kv: -len(kv[1]))[:25]:
        t = [s for s in rows if _tight(s)]
        lb = bets_by_league.get(lg, [])
        leagues.append({"name": lg, "n": len(rows), "real": len(t) / len(rows), "gap": _mean(abs(_mid(s) - s["fair"]) for s in t),
                        "edge": _share_edge(t), "bets": len(lb), "clv": _mean(b.get("clv") for b in lb),
                        "profit": round(sum(b["profit"] for b in lb if b.get("profit") is not None), 2)})

    return {
        "updated": iso(now), "repo": repo_slug(root),
        "rules": {"bankroll": start, "stake": float(g["stake_usd"]), "min_edge": float(g["min_edge"]),
                  "max_edge": float(g["max_edge"]), "mode": g.get("mode", "hourly"), "every": g["every_minutes"],
                  "poll": g.get("poll_seconds", 5)},
        "status": {"last_run": state.get("last_run"), "calls_today": state.get("calls"), "day": state.get("day")},
        "account": {"start": start, "balance": balance, "realized": round(realized, 2), "cash": round(cash, 2),
                    "projected": projected, "open_n": len(open_rows), "open_cost": round(sum(r["cost"] for r in open_rows), 2),
                    "settled_n": len(done), "wins": sum(b["result"] == b["side"] for b in done),
                    "losses": sum(b["result"] != b["side"] for b in done), "placed_n": len(placed),
                    "missed_n": len(missed), "unknown_n": len(unknown), "no_cash_n": len(no_cash),
                    "same_game_n": len(same_game),
                    "compare": {"n": len(done), "hold": round(sum(b["profit"] for b in done), 2),
                                "early": round(sum(b["exit_profit"] if b.get("exit_profit") is not None else b["profit"]
                                                   for b in done), 2),
                                "sold": sum(b.get("exit_profit") is not None for b in done),
                                "sold_open": sum(r["exit_profit"] is not None for r in open_rows)},
                    "clv": _mean(b["clv"] for b in scored), "clv_n": len(scored),
                    "clv_usd": round(sum(b["clv"] * b["n"] for b in scored), 2)},
        "real_line": real_line, "proj_line": proj_line,
        "open": open_rows, "settled": settled_rows, "missed": missed_rows,
        "scan": {"rows": len(snaps), "since": first if snaps else None, "real": (len(tight) / len(snaps)) if snaps else None,
                 "gap": _mean(abs(_mid(s) - s["fair"]) for s in tight), "edge": _share_edge(tight) if tight else None,
                 "leagues": leagues},
        "moves": move_stats(read_jsonl(data / "gap_moves.jsonl")) if (data / "gap_moves.jsonl").exists() else [],
    }


def render(data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":"), default=str)
    payload = (payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return TEMPLATE.read_text().replace("/*__DATA__*/null", payload, 1)


def write_site(root: Path, cfg: dict, now: datetime | None = None, page: bool = True) -> dict:
    """site/gaps.json always; site/index.html too unless page=False (a new page means a Pages deploy)."""
    data = build_data(root, cfg, now)
    out = Path(root) / "site"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gaps.json").write_text(json.dumps(data, separators=(",", ":"), default=str) + "\n")
    if page:
        (out / "index.html").write_text(render(data))
    return data
