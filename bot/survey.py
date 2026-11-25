"""Market-type survey: which kinds of Kalshi markets are slow, tradable and mispriced?

    python -m bot survey [--days 3] [--per-series 4]

For every series (market type, e.g. KXRAIN or KXAAAGASD) it measures:
- tradability, from open markets now: how many, 24h volume, bid-ask spread, contracts on
  offer at the best price (can a $100 bet fill?);
- speed, from a sample of recently settled markets' minute-by-minute prices: how often the
  quote changes and how often anything trades in the final 24 hours;
- accuracy, from the same sample: how far the price was from the result 6 hours and 1 hour
  before close, and the profit from buying the favourite then at the real ask after fees;
- jumps: what followed sudden 10c moves (same measure as the lag scanner).

Writes NICHES.md (tables) and data/niche_survey.json (everything). Read-only: nothing is traded.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from .journal import Journal
from .kalshi import KalshiClient, KalshiError
from .lags import analyse, mid, quote_track, series_of
from .strategy import quotes
from .util import iso, parse_time, to_float, utcnow

MIN_SAMPLE_VOLUME = 200     # contracts over a settled market's life, to be worth sampling
LOOKBACK_HOURS = 24
FAST_CATEGORIES = ("Sports", "Crypto")   # thousands of markets a day; sample fewer of each type
MAX_CANDLE_CALLS = 1800


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def activity(candles: list[dict], start_ts: int, end_ts: int) -> dict:
    """How alive the price was: quote changes and minutes with trades, per hour."""
    rows = []
    for c in candles:
        t = c.get("end_period_ts")
        if t is None:
            continue
        rows.append((int(t), to_float((c.get("yes_bid") or {}).get("close_dollars")),
                     to_float((c.get("yes_ask") or {}).get("close_dollars")), to_float(c.get("volume_fp"), 0.0)))
    rows.sort()
    changes, traded, prev = 0, 0, None
    for _, bid, ask, vol in rows:
        if vol and vol > 0:
            traded += 1
        if bid is None or ask is None:
            continue
        if prev is not None and (bid, ask) != prev:
            changes += 1
        prev = (bid, ask)
    hours = max((end_ts - start_ts) / 3600, 1 / 60)
    return {"quote_changes_per_hour": round(changes / hours, 2), "trade_minutes_per_hour": round(traded / hours, 2)}


def accuracy(track: list, result: str) -> dict:
    """Squared error of the mid price vs the result (0 = spot on, 0.25 = a coin flip's worth)."""
    y = 1.0 if result == "yes" else 0.0
    n, out = len(track), {}
    for label, minutes in (("6h", 360), ("1h", 60)):
        i = n - 1 - minutes
        m = mid(track[i]) if 0 <= i < n else None
        out[f"err_{label}"] = None if m is None else round((m - y) ** 2, 4)
    return out


def _pick(cands: list[dict], k: int) -> list[dict]:
    """k markets from different events, chosen pseudo-randomly but repeatably."""
    order = sorted(cands, key=lambda m: hashlib.md5(m["ticker"].encode()).hexdigest())
    seen, out = set(), []
    for m in order:
        if m.get("event_ticker") in seen:
            continue
        seen.add(m.get("event_ticker"))
        out.append(m)
        if len(out) >= k:
            break
    return out


def survey(kalshi: KalshiClient, journal: Journal, now: datetime | None = None, days: float = 3,
           per_series: int = 4, say=print) -> dict:
    now = now or utcnow()
    # 1) tradability, from open markets
    opn = defaultdict(lambda: {"open": 0, "vol24": 0.0, "spreads": [], "depth": [], "tight": 0})
    n_open = 0
    for m in kalshi.iter_markets(max_markets=300000, status="open", mve_filter="exclude"):
        n_open += 1
        g = opn[series_of(m)]
        g["open"] += 1
        g["vol24"] += to_float(m.get("volume_24h_fp"), 0.0)
        q = quotes(m)
        if q.spread is not None and q.yes_bid and q.yes_ask and 0 < q.yes_bid < q.yes_ask < 1:
            g["spreads"].append(q.spread)
            g["depth"].append(min(q.yes_bid_size or 0, q.yes_ask_size or 0))
            g["tight"] += q.spread <= 0.03
    say(f"Survey: {n_open} open markets in {len(opn)} market types")

    # 2) recently settled markets, grouped by type
    lo, hi = now - timedelta(days=days), now - timedelta(minutes=30)
    sett = defaultdict(lambda: {"settled": 0, "volume": 0.0, "cands": []})
    n_set = 0
    for m in kalshi.iter_markets(max_markets=600000, status="settled", mve_filter="exclude",
                                 min_close_ts=int(lo.timestamp()), max_close_ts=int(hi.timestamp())):
        if m.get("result") not in ("yes", "no"):
            continue
        n_set += 1
        g = sett[series_of(m)]
        g["settled"] += 1
        v = to_float(m.get("volume_fp"), 0.0)
        g["volume"] += v
        if v >= MIN_SAMPLE_VOLUME and len(g["cands"]) < 60:
            g["cands"].append({k: m.get(k) for k in ("ticker", "event_ticker", "result", "close_time",
                                                     "open_time", "title", "volume_fp")})
    say(f"Survey: {n_set} markets settled in the last {days:g} days, {len(sett)} market types")

    # 3) category and name for each type worth sampling (cached across runs)
    cats = dict(journal.state.get("series_categories", {}))
    for s in sorted(k for k, g in sett.items() if g["cands"]):
        if s not in cats or f"title:{s}" not in cats:
            try:
                info = kalshi.get_series(s)
                cats[s], cats[f"title:{s}"] = info.get("category") or "Other", info.get("title") or s
            except KalshiError:
                cats.setdefault(s, "Other")
    journal.set_state("series_categories", cats)

    # 4) sample settled markets of each type: speed, accuracy, jumps
    plan = []
    for s, g in sett.items():
        k = min(2, per_series) if cats.get(s) in FAST_CATEGORIES else per_series
        plan += [(s, m) for m in _pick(g["cands"], k)]
    plan.sort(key=lambda x: (cats.get(x[0]) in FAST_CATEGORIES, x[0]))   # niche types first if we hit the cap
    plan = plan[:MAX_CANDLE_CALLS]
    samples = defaultdict(list)
    for s, m in plan:
        close, opened = parse_time(m.get("close_time")), parse_time(m.get("open_time"))
        if not close:
            continue
        begin = max(close - timedelta(hours=LOOKBACK_HOURS), opened or close - timedelta(hours=LOOKBACK_HOURS))
        s_ts, e_ts = int(begin.timestamp()) // 60 * 60, int(close.timestamp()) // 60 * 60
        if e_ts - s_ts < 3600:
            continue
        try:
            d = kalshi.request("GET", f"/series/{s}/markets/{m['ticker']}/candlesticks",
                               params={"start_ts": s_ts, "end_ts": e_ts, "period_interval": 1})
        except KalshiError:
            continue
        candles = d.get("candlesticks") or []
        track = quote_track(candles, s_ts, e_ts)
        a = analyse(track, m["result"])
        samples[s].append({"ticker": m["ticker"], **activity(candles, s_ts, e_ts), **accuracy(track, m["result"]),
                           "late_1h": (a["late"].get("1h") or {}).get("profit"),
                           "late_6h": (a["late"].get("6h") or {}).get("profit"),
                           "jumps": a["jumps"], "spread": a["median_spread"]})
    say(f"Survey: sampled {sum(len(v) for v in samples.values())} settled markets across {len(samples)} types")

    # 5) one row per market type
    rows = []
    for s in set(opn) | set(sett):
        o, g, smp = opn.get(s), sett.get(s), samples.get(s, [])
        if not smp and not (o and o["vol24"] > 0):
            continue
        jumps = [j for x in smp for j in x["jumps"]]
        rows.append({
            "series": s, "name": cats.get(f"title:{s}") or s, "category": cats.get(s) or "Other",
            "open_markets": o["open"] if o else 0,
            "vol24_per_open_market": round(o["vol24"] / o["open"], 1) if o and o["open"] else None,
            "open_spread": _med(o["spreads"]) if o else None,
            "open_depth": _med(o["depth"]) if o else None,
            "open_tight_share": round(o["tight"] / len(o["spreads"]), 2) if o and o["spreads"] else None,
            "settled": g["settled"] if g else 0, "settled_per_day": round((g["settled"] if g else 0) / days, 1),
            "settled_volume_per_market": round(g["volume"] / g["settled"], 1) if g and g["settled"] else None,
            "sampled": len(smp),
            "quote_changes_per_hour": _med([x["quote_changes_per_hour"] for x in smp]),
            "trade_minutes_per_hour": _med([x["trade_minutes_per_hour"] for x in smp]),
            "err_6h": _mean([x["err_6h"] for x in smp]), "err_1h": _mean([x["err_1h"] for x in smp]),
            "late_6h": _mean([x["late_6h"] for x in smp]), "late_1h": _mean([x["late_1h"] for x in smp]),
            "jumps": len(jumps), "follow": _mean([j["follow"] for j in jumps]), "fade": _mean([j["fade"] for j in jumps]),
            "examples": [x["ticker"] for x in smp][:3],
        })
    rows.sort(key=lambda r: (r["category"], r["series"]))
    return {"generated": iso(now), "days": days, "open_markets": n_open, "settled_markets": n_set, "series": rows}


# ---- report ----------------------------------------------------------------------------------
def tradable(r: dict) -> bool:
    """Could a $100 bet realistically fill near the quoted price right now?"""
    return (r["open_markets"] > 0 and r["open_spread"] is not None and r["open_spread"] <= 0.06
            and (r["open_depth"] or 0) >= 50)


def _f(x, fmt="{:.1f}", none="–"):
    return none if x is None else fmt.format(x)


def _c(x):
    return "–" if x is None else f"{x * 100:+.1f}¢"


def report_markdown(data: dict) -> str:
    rows = data["series"]
    sampled = [r for r in rows if r["sampled"] >= 2]
    slow = sorted([r for r in sampled if tradable(r) and r["category"] not in FAST_CATEGORIES],
                  key=lambda r: (r["quote_changes_per_hour"] if r["quote_changes_per_hour"] is not None else 99))
    shaky = sorted([r for r in sampled if tradable(r) and r["err_6h"] is not None],
                   key=lambda r: -r["err_6h"])
    lines = [
        "# Slow, niche Kalshi markets", "",
        f"*Survey of {data['open_markets']:,} open markets and {data['settled_markets']:,} that settled in the last "
        f"{data['days']:g} days ({data['generated'][:16].replace('T', ' ')} UTC). For each market type: how busy and how "
        "tradable it is now, and, from a sample of settled markets' minute-by-minute prices, how often the price moved, how "
        "accurate it was before close, and whether buying the favourite late paid. Read-only research; not financial advice.*", "",
        "**Columns:** *Price moves/h* = how often the best bid or ask changed per hour in the final day (low = slow). "
        "*Trades/h* = minutes with any trade per hour. *Spread* and *Depth* = the gap between bid and ask, and contracts on "
        "offer at the best price, on open markets now (a $100 bet needs roughly 100-300). *Error 6h* = squared gap between "
        "the price 6 hours before close and the result (0 = spot on, 0.25 = coin flip). *Fav 6h/1h* = profit per $1 from "
        "buying the favourite then at the ask, after fees. *Sample* = settled markets measured.", "",
        "## Slowest market types you could actually trade", "",
        "(Not sports or crypto; spread 6c or less and 50+ contracts on offer now.)", "",
        "| Market type | Category | Open now | Price moves/h | Trades/h | Spread | Depth | Error 6h | Fav 6h | Fav 1h | Sample |",
        "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in slow[:40]:
        lines.append(f"| {r['name']} (`{r['series']}`) | {r['category']} | {r['open_markets']} | "
                     f"{_f(r['quote_changes_per_hour'])} | {_f(r['trade_minutes_per_hour'])} | {_c(r['open_spread']).lstrip('+')} | "
                     f"{_f(r['open_depth'], '{:,.0f}')} | {_f(r['err_6h'], '{:.3f}')} | {_c(r['late_6h'])} | {_c(r['late_1h'])} | {r['sampled']} |")
    lines += ["", "## Where prices were least accurate 6 hours before close (tradable types)", "",
              "| Market type | Category | Error 6h | Error 1h | Fav 6h | Price moves/h | Sample |", "|---|---|---|---|---|---|---|"]
    for r in shaky[:25]:
        lines.append(f"| {r['name']} (`{r['series']}`) | {r['category']} | {_f(r['err_6h'], '{:.3f}')} | "
                     f"{_f(r['err_1h'], '{:.3f}')} | {_c(r['late_6h'])} | {_f(r['quote_changes_per_hour'])} | {r['sampled']} |")
    cats = defaultdict(list)
    for r in sampled:
        cats[r["category"]].append(r)
    lines += ["", "## By category (median of market types)", "",
              "| Category | Types sampled | Tradable now | Price moves/h | Trades/h | Error 6h | Fav 6h |", "|---|---|---|---|---|---|---|"]
    for c, rs in sorted(cats.items(), key=lambda kv: _med([r["quote_changes_per_hour"] for r in kv[1]]) or 0):
        lines.append(f"| {c} | {len(rs)} | {sum(tradable(r) for r in rs)} | {_f(_med([r['quote_changes_per_hour'] for r in rs]))} | "
                     f"{_f(_med([r['trade_minutes_per_hour'] for r in rs]))} | {_f(_med([r['err_6h'] for r in rs]), '{:.3f}')} | "
                     f"{_c(_med([r['late_6h'] for r in rs]))} |")
    lines += ["", "*Small samples per type (2-4 markets) make single numbers noisy; treat this as a shortlist to test, "
                  "not a verdict.*", ""]
    return "\n".join(lines)
