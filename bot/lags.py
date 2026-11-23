"""Lag scanner: in which kinds of Kalshi markets do prices keep drifting after news hits?

It never sees the news itself. It looks at minute-by-minute prices of markets that have
already settled, finds sudden moves (10 cents or more within 5 minutes, i.e. something
happened), and measures what came next:

- drift:   did the price keep moving the same way 5, 30 and 60 minutes later? If so, the
           market was slow to finish reacting.
- follow:  profit per $1 contract from betting in the direction of the move one minute
           later, at the real ask price, after Kalshi's fee, held to settlement.
- fade:    the same for betting against the move (positive = the market overreacts).
- late:    profit from buying the favourite 1 hour before close (positive = outcomes that
           were close to known still weren't fully priced).

Every bot run scans markets that settled since the last scan, a sample from every category,
and appends one row per market to data/lag_scan.jsonl. LAGS.md and the results page rank
categories and market types. No Claude, no tokens, nothing is traded.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from .journal import Journal
from .kalshi import KalshiClient, KalshiError
from .strategy import fee_per_contract
from .util import iso, parse_time, to_float, utcnow

JUMP_CENTS = 0.10          # a move of at least 10 cents...
JUMP_MINUTES = 5           # ...within 5 minutes counts as news arriving
GAP_MINUTES = 30           # at most one jump per 30 minutes per market
MAX_JUMPS_PER_MARKET = 5   # so one wild market can't dominate
MAX_SPREAD = 0.10          # ignore quotes wider than this
FILL_MINUTES = 12 * 60     # minutes with no candle keep the last quote (it was still standing), up to 12 hours
HORIZONS = (5, 30, 60)
LOOKBACK_HOURS = 48        # price history read before each market's close
MIN_VOLUME = 1000          # contracts traded over the market's life
SOLID_N = 30               # results from fewer jumps than this are labelled "early"


def series_of(m: dict) -> str:
    return m.get("series_ticker") or (m.get("event_ticker") or m.get("ticker") or "").split("-")[0]


# ---- prices ----------------------------------------------------------------------------
def quote_track(candles: list[dict], start_ts: int, end_ts: int) -> list[tuple[float, float] | None]:
    """One (yes_bid, yes_ask) per minute from start_ts to end_ts, forward-filled for up to
    FILL_MINUTES when a minute has no candle. None where there's no usable quote."""
    by_min = {}
    for c in candles:
        t = c.get("end_period_ts")
        bid = to_float((c.get("yes_bid") or {}).get("close_dollars"))
        ask = to_float((c.get("yes_ask") or {}).get("close_dollars"))
        if t is not None and bid is not None and ask is not None:
            by_min[(int(t) - start_ts) // 60] = (bid, ask)
    n = max(0, (end_ts - start_ts) // 60)
    out, last, age = [], None, 0
    for i in range(n + 1):
        if i in by_min:
            last, age = by_min[i], 0
        else:
            age += 1
        q = last if last is not None and age <= FILL_MINUTES else None
        out.append(q if q and 0.0 < q[0] < q[1] < 1.0 and q[1] - q[0] <= MAX_SPREAD else None)
    return out


def mid(q):
    return None if q is None else (q[0] + q[1]) / 2


def buy_cost(q, side: str) -> float | None:
    """What one contract of `side` costs at the ask, including Kalshi's fee."""
    if q is None:
        return None
    price = q[1] if side == "yes" else 1 - q[0]
    return price + fee_per_contract(price)


def profit(q, side: str, result: str) -> float | None:
    cost = buy_cost(q, side)
    return None if cost is None else (1.0 if side == result else 0.0) - cost


def analyse(track: list, result: str) -> dict:
    """Jumps and what followed, plus the late-favourite check, for one settled market."""
    n = len(track)
    mids = [mid(q) for q in track]
    jumps, last_jump = [], -10 ** 9
    for i in range(JUMP_MINUTES, n - 10):
        if len(jumps) >= MAX_JUMPS_PER_MARKET:
            break
        a, b = mids[i - JUMP_MINUTES], mids[i]
        if a is None or b is None or abs(b - a) < JUMP_CENTS or i - last_jump < GAP_MINUTES:
            continue
        d = 1 if b > a else -1
        side, other = ("yes", "no") if d > 0 else ("no", "yes")
        row = {"min_before_close": n - 1 - i, "from": round(a, 3), "to": round(b, 3)}
        for k in HORIZONS:
            later = mids[i + k] if i + k < n else None
            row[f"d{k}"] = None if later is None else round(d * (later - b), 4)
        entry = track[i + 1] if i + 1 < n else None
        f, g = profit(entry, side, result), profit(entry, other, result)
        row["follow"] = None if f is None else round(f, 4)
        row["fade"] = None if g is None else round(g, 4)
        jumps.append(row)
        last_jump = i
    late = {}
    for label, minutes in (("1h", 60), ("6h", 360)):
        i = n - 1 - minutes
        q = track[i] if 0 <= i < n else None
        m = mid(q)
        if m is None:
            continue
        fav = "yes" if m >= 0.5 else "no"
        late[label] = {"fav_price": round(m if fav == "yes" else 1 - m, 3),
                       "profit": round(profit(q, fav, result), 4), "upset": fav != result}
    spreads = [q[1] - q[0] for q in track if q]
    return {"jumps": jumps, "late": late, "quoted_minutes": len(spreads),
            "median_spread": round(statistics.median(spreads), 3) if spreads else None}


# ---- choosing what to scan ----------------------------------------------------------------
def pick_markets(markets: list[dict], categories: dict[str, str], per_category: int,
                 per_series: int = 3) -> list[dict]:
    """A spread across categories: the busiest markets in each, at most one per event and a
    few per series, so sports and crypto (thousands a day) don't crowd out everything else."""
    by_cat = defaultdict(list)
    for m in sorted(markets, key=lambda m: to_float(m.get("volume_fp"), 0.0), reverse=True):
        if m.get("result") not in ("yes", "no") or to_float(m.get("volume_fp"), 0.0) < MIN_VOLUME:
            continue
        by_cat[categories.get(series_of(m)) or "Other"].append(m)
    picked = []
    for cat, ms in by_cat.items():
        events, series, take = set(), Counter(), []
        for m in ms:
            s, ev = series_of(m), m.get("event_ticker")
            if ev in events or series[s] >= per_series:
                continue
            events.add(ev)
            series[s] += 1
            take.append(m)
            if len(take) >= per_category:
                break
        picked += take
    return picked


def scan(kalshi: KalshiClient, journal: Journal, now: datetime | None = None, hours: float | None = None,
         per_category: int = 20, say=print) -> int:
    now = now or utcnow()
    until = parse_time(journal.state.get("lag_scan_until"))
    start = now - timedelta(hours=hours) if hours else (until or now - timedelta(hours=24))
    start = max(start, now - timedelta(days=3))
    end = now - timedelta(minutes=30)          # give settlement a little time
    if end <= start:
        say("Lag scan: nothing new to scan yet")
        return 0
    markets = list(kalshi.iter_markets(max_markets=60000, status="settled", mve_filter="exclude",
                                       min_close_ts=int(start.timestamp()), max_close_ts=int(end.timestamp())))
    categories = dict(journal.state.get("series_categories", {}))
    for s in sorted({series_of(m) for m in markets
                     if to_float(m.get("volume_fp"), 0.0) >= MIN_VOLUME and m.get("result") in ("yes", "no")}):
        if s and s not in categories:
            try:
                info = kalshi.get_series(s)
                categories[s] = info.get("category") or "Other"
                categories[f"title:{s}"] = info.get("title") or s
            except KalshiError:
                categories[s] = "Other"
    journal.set_state("series_categories", categories)
    done = {r["ticker"] for r in journal.rows.get("lag_scan", [])}
    picked = [m for m in pick_markets(markets, categories, per_category) if m["ticker"] not in done]
    scanned = 0
    for m in picked:
        close = parse_time(m.get("close_time"))
        opened = parse_time(m.get("open_time"))
        if not close:
            continue
        begin = max(close - timedelta(hours=LOOKBACK_HOURS), opened or close - timedelta(hours=LOOKBACK_HOURS))
        s_ts, e_ts = int(begin.timestamp()) // 60 * 60, int(close.timestamp()) // 60 * 60
        try:
            d = kalshi.request("GET", f"/series/{series_of(m)}/markets/{m['ticker']}/candlesticks",
                               params={"start_ts": s_ts, "end_ts": e_ts, "period_interval": 1})
        except KalshiError as e:
            say(f"Lag scan: no price history for {m['ticker']}: {str(e)[:120]}")
            continue
        result = analyse(quote_track(d.get("candlesticks") or [], s_ts, e_ts), m["result"])
        s = series_of(m)
        journal.append("lag_scan", {
            "ts": iso(now), "ticker": m["ticker"], "event_ticker": m.get("event_ticker"), "series": s,
            "series_title": categories.get(f"title:{s}") or s, "category": categories.get(s) or "Other",
            "title": m.get("title"), "close_time": m.get("close_time"), "result": m["result"],
            "volume": to_float(m.get("volume_fp"), 0.0), **result})
        scanned += 1
    journal.set_state("lag_scan_until", iso(end))
    jumps = sum(len(r.get("jumps", [])) for r in journal.rows["lag_scan"][-scanned:]) if scanned else 0
    say(f"Lag scan: {len(markets)} markets settled since {start:%b %d %H:%M} UTC; scanned {scanned} "
        f"across {len({categories.get(series_of(m)) for m in picked})} categories, {jumps} price jumps found")
    return scanned


# ---- summarising -----------------------------------------------------------------------------
def _stat(values: list[float]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "se": None}
    se = statistics.stdev(vals) / math.sqrt(len(vals)) if len(vals) > 1 else None
    return {"n": len(vals), "mean": statistics.fmean(vals), "se": se}


def group_summary(rows: list[dict]) -> dict:
    jumps = [j for r in rows for j in r.get("jumps", [])]
    out = {"markets": len(rows), "jumps": len(jumps), "volume": sum(r.get("volume", 0) for r in rows)}
    for k in HORIZONS:
        out[f"d{k}"] = _stat([j.get(f"d{k}") for j in jumps])
    out["follow"] = _stat([j.get("follow") for j in jumps])
    out["fade"] = _stat([j.get("fade") for j in jumps])
    out["late"] = _stat([(r.get("late") or {}).get("1h", {}).get("profit") for r in rows])
    spreads = [r["median_spread"] for r in rows if r.get("median_spread") is not None]
    out["spread"] = statistics.median(spreads) if spreads else None
    return out


def verdict(s: dict) -> str:
    """Plain-English read of a group: is the drift / profit clearly there yet?"""
    f, d = s["follow"], s["d30"]
    if f["n"] < SOLID_N:
        return "early"
    clear = f["se"] is not None and abs(f["mean"]) > 2 * f["se"]
    if clear and f["mean"] > 0:
        return "lags"
    if clear and f["mean"] < 0 and s["fade"]["mean"] is not None and s["fade"]["mean"] > 0:
        return "overreacts"
    if d["n"] >= SOLID_N and d["se"] and d["mean"] > 2 * d["se"]:
        return "drifts"
    return "keeps up"


def summarize(rows: list[dict], top: int = 10) -> dict:
    by_cat, by_series = defaultdict(list), defaultdict(list)
    for r in rows:
        by_cat[r.get("category") or "Other"].append(r)
        by_series[r.get("series")].append(r)
    cats = []
    for c, rs in by_cat.items():
        s = group_summary(rs)
        cats.append({"name": c, **s, "verdict": verdict(s)})
    cats.sort(key=lambda x: (x["follow"]["mean"] if x["follow"]["n"] else -9), reverse=True)
    series = []
    for k, rs in by_series.items():
        s = group_summary(rs)
        if s["follow"]["n"] >= 8:
            series.append({"name": rs[-1].get("series_title") or k, "ticker": k,
                           "category": rs[-1].get("category"), **s, "verdict": verdict(s)})
    series.sort(key=lambda x: x["follow"]["mean"], reverse=True)
    first = min((r.get("ts") for r in rows), default=None)
    return {"markets": len(rows), "jumps": sum(len(r.get("jumps", [])) for r in rows), "since": first,
            "categories": cats, "series_top": series[:top], "series_bottom": series[-top:][::-1] if len(series) > top else []}


def _c(x) -> str:
    return "–" if x is None else f"{x * 100:+.1f}¢"


def report_markdown(summary: dict) -> str:
    lines = ["# Where Kalshi prices lag", "",
             "*Built from minute-by-minute prices of markets that already settled. A **jump** is a move of "
             "10¢+ within 5 minutes (news arriving). **Drift** is how much further the price kept moving the same "
             "way afterwards. **Follow** is the profit per $1 contract from betting with the jump one minute later, "
             "at the real ask price, after fees, held to settlement. **Fade** is betting against it. **Late** is "
             "buying the favourite an hour before close. Positive follow or drift = the market is slow there.*", "",
             f"{summary['markets']} markets and {summary['jumps']} jumps scanned"
             + (f" since {summary['since'][:10]}" if summary.get("since") else "") + ".", "",
             "## By category", "",
             "| Category | Markets | Jumps | Drift 5 min | Drift 30 min | Drift 60 min | Follow | Fade | Late | Read |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for c in summary["categories"]:
        lines.append(f"| {c['name']} | {c['markets']} | {c['jumps']} | {_c(c['d5']['mean'])} | {_c(c['d30']['mean'])} | "
                     f"{_c(c['d60']['mean'])} | {_c(c['follow']['mean'])} | {_c(c['fade']['mean'])} | "
                     f"{_c(c['late']['mean'])} | {c['verdict']} |")
    for title, key in (("Market types where following a jump paid best", "series_top"),
                       ("Market types where it paid worst", "series_bottom")):
        if summary.get(key):
            lines += ["", f"## {title}", "", "| Market type | Category | Jumps | Drift 30 min | Follow | Read |",
                      "|---|---|---|---|---|---|"]
            for s in summary[key]:
                lines.append(f"| {s['name']} (`{s['ticker']}`) | {s['category']} | {s['jumps']} | {_c(s['d30']['mean'])} | "
                             f"{_c(s['follow']['mean'])} | {s['verdict']} |")
    lines += ["", "*Reads: **lags** = following jumps clearly paid; **drifts** = prices clearly kept moving, but not by "
                  "enough to beat the spread and fees yet; **overreacts** = fading paid; **keeps up** = no clear edge; "
                  f"**early** = fewer than {SOLID_N} jumps so far. \"Clearly\" means more than two standard errors from zero. "
                  "Past patterns can fade, and this is pretend-money research, not financial advice.*", ""]
    return "\n".join(lines)


# ---- probe (read-only) ----------------------------------------------------------------------
def probe(kalshi: KalshiClient, say=print) -> None:
    now = utcnow()
    lo, hi = int((now - timedelta(hours=6)).timestamp()), int(now.timestamp())
    ms = list(kalshi.iter_markets(max_markets=5000, status="settled", min_close_ts=lo, max_close_ts=hi,
                                  mve_filter="exclude"))
    say(f"settled in the last 6h: {len(ms)}")
    if ms:
        m = max(ms, key=lambda m: to_float(m.get("volume_fp"), 0.0))
        say(json.dumps({k: m.get(k) for k in ("ticker", "event_ticker", "result", "close_time", "volume_fp")}))
