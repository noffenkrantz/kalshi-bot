"""Deep survey of Kalshi's daily high / low temperature markets.

    python -m bot tempsurvey --probe     what the markets' rules, brackets and times look like
    python -m bot tempsurvey --days 14   the full survey: writes TEMPS.md and data/temp_survey.json

The key test: once a city's own station readings already decide a bracket (a reading of 70
means the day's high can't be "67-68"), how often was that bracket still cheap on Kalshi, for
how long, and what would buying it then have made after fees?

Read-only research; nothing is traded.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import timedelta

import requests

from .kalshi import KalshiClient, KalshiError
from .util import utcnow

IEM = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"


def temp_series(kalshi: KalshiClient) -> list[str]:
    """Every series of daily high or low temperature markets with recent activity."""
    found = Counter()
    now = utcnow()
    for status, extra in (("open", {}), ("settled", {"min_close_ts": int((now - timedelta(days=3)).timestamp())})):
        for m in kalshi.iter_markets(max_markets=400000, status=status, mve_filter="exclude", **extra):
            s = (m.get("event_ticker") or "").split("-")[0]
            if s.startswith(("KXHIGH", "KXLOWT")):
                found[s] += 1
    return sorted(found)


def probe(kalshi: KalshiClient, say=print) -> None:
    now = utcnow()
    series = temp_series(kalshi)
    say(f"# Temperature probe {now:%Y-%m-%d %H:%M} UTC: {len(series)} series\n{series}\n")
    for s in series:
        try:
            info = kalshi.get_series(s)
        except KalshiError as e:
            say(f"{s}: {e}")
            continue
        ms = list(kalshi.iter_markets(max_markets=60, series_ticker=s, status="settled",
                                      min_close_ts=int((now - timedelta(days=2)).timestamp())))
        say(f"## {s} | {info.get('title')} | sources {json.dumps(info.get('settlement_sources'))[:300]} | {len(ms)} settled in 2 days")
        ev = Counter(m.get("event_ticker") for m in ms)
        if not ms:
            continue
        first_ev = ms[0].get("event_ticker")
        for m in [x for x in ms if x.get("event_ticker") == first_ev][:8]:
            say(f"   {m['ticker']} | sub '{m.get('yes_sub_title')}' | {m.get('strike_type')} floor={m.get('floor_strike')} "
                f"cap={m.get('cap_strike')} | result {m.get('result')} | open {m.get('open_time')} close {m.get('close_time')} "
                f"| vol {m.get('volume_fp')}")
        say(f"   rules: {(ms[0].get('rules_primary') or '')[:400]}")
        say(f"   more: {(ms[0].get('rules_secondary') or '')[:300]}")
        say(f"   markets per event: {sorted(ev.values())}")
    # is the historical observation archive reachable?
    try:
        r = requests.get(IEM, params={"station": "NYC", "data": "tmpf", "year1": now.year, "month1": now.month,
                                      "day1": (now - timedelta(days=1)).day, "year2": now.year, "month2": now.month,
                                      "day2": now.day, "tz": "Etc/UTC", "format": "onlycomma", "latlon": "no",
                                      "missing": "M", "report_type": [3, 4]}, timeout=60)
        say(f"\nIEM archive: HTTP {r.status_code}, {len(r.text.splitlines())} lines; first lines:\n" + "\n".join(r.text.splitlines()[:5]))
    except requests.RequestException as e:
        say(f"\nIEM archive unreachable: {e}")


# ==== the full survey ==========================================================================
import csv
import io
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from .journal import Journal
from .lags import analyse, quote_track
from .nws import NWSClient, NWSError, climate_day_bounds
from .strategy import fee_per_contract
from .util import iso, parse_time, to_float

LATENCY_MIN = 5          # a station reading is assumed usable 5 minutes after its timestamp
CAUGHT_UP = 0.97         # the market has "caught up" once the decided side costs 97c or more
HOURS = (9, 12, 15, 18, 21)
_MON = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def kind_of(series: str) -> str:
    return "low" if series.startswith("KXLOWT") else "high"


def event_day(event_ticker: str) -> date | None:
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})$", event_ticker or "")
    if not m or m.group(2) not in _MON:
        return None
    return date(2000 + int(m.group(1)), _MON[m.group(2)], int(m.group(3)))


def bracket(m: dict) -> tuple[int | None, int | None] | None:
    """Inclusive whole-degree range that resolves YES. 'greater' floor 68 = 69 or above, etc."""
    st, f, c = m.get("strike_type"), to_float(m.get("floor_strike")), to_float(m.get("cap_strike"))
    if st == "greater" and f is not None:
        return (int(math.floor(f)) + 1, None)
    if st == "less" and c is not None:
        return (None, int(math.ceil(c)) - 1)
    if st == "between" and f is not None and c is not None:
        return (int(f), int(c))
    return None


def cli_station(m: dict) -> str | None:
    found = re.search(r"\(CLI([A-Z0-9]{3,4})\)", m.get("rules_primary") or "")
    return found.group(1) if found else None


def lock(kind: str, br: tuple, obs: list[tuple[datetime, float]], margin: int) -> tuple[datetime, str] | None:
    """First reading after which the station's own data already decides this bracket.
    The official max can't be below a reading (or the min above one), so a high of 70 kills
    '67-68' and makes '69 or above' YES. margin=1 demands one extra degree (rounding safety)."""
    lo, hi = br
    run = None
    for t, temp in obs:
        run = temp if run is None else (max(run, temp) if kind == "high" else min(run, temp))
        r = round(run)
        if kind == "high":
            if hi is None and r >= lo + margin:
                return t, "yes"
            if hi is not None and r >= hi + 1 + margin:
                return t, "no"
        else:
            if lo is None and r <= hi - margin:
                return t, "yes"
            if lo is not None and r <= lo - 1 - margin:
                return t, "no"
    return None


def raw_track(candles: list[dict], start_ts: int, end_ts: int) -> list[tuple[float | None, float | None]]:
    """(yes_bid, yes_ask) for every minute, carried forward; None parts mean nothing on that side."""
    by_min = {}
    for c in candles:
        t = c.get("end_period_ts")
        if t is None:
            continue
        by_min[(int(t) - start_ts) // 60] = (to_float((c.get("yes_bid") or {}).get("close_dollars")),
                                             to_float((c.get("yes_ask") or {}).get("close_dollars")),
                                             to_float(c.get("volume_fp"), 0.0))
    out, last = [], (None, None, 0.0)
    for i in range((end_ts - start_ts) // 60 + 1):
        if i in by_min:
            last = by_min[i]
            out.append(last)
        else:
            out.append((last[0], last[1], 0.0))
    return out


def side_cost(q, side: str) -> float:
    """What one contract of the decided side costs right then (1.0 = nobody selling)."""
    bid, ask, _ = q
    if side == "yes":
        return ask if ask is not None and 0 < ask < 1 else 1.0
    return 1 - bid if bid is not None and 0 < bid < 1 else 1.0


def iem_observations(code: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    """Hourly and special station reports (what a live watcher would see), from the Iowa
    Environmental Mesonet archive of NWS station data."""
    r = requests.get(IEM, params={"station": code, "data": "tmpf", "year1": start.year, "month1": start.month,
                                  "day1": start.day, "year2": end.year, "month2": end.month, "day2": end.day,
                                  "tz": "Etc/UTC", "format": "onlycomma", "latlon": "no", "missing": "M",
                                  "report_type": [3, 4]}, timeout=120)
    r.raise_for_status()
    out = []
    for row in csv.DictReader(io.StringIO(r.text)):
        v = to_float(row.get("tmpf"))
        if v is None:
            continue
        t = datetime.strptime(row["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        out.append((t, v))
    return sorted(out)


def orderbook_depth(kalshi: KalshiClient, ticker: str, within: float = 0.03) -> dict | None:
    """Contracts you could buy within 3c of the best price, for YES and for NO."""
    try:
        d = kalshi.request("GET", f"/markets/{ticker}/orderbook")
        ob = d.get("orderbook_fp") or d.get("orderbook") or {}
    except KalshiError:
        return None

    def levels(key):
        rows = ob.get(f"{key}_dollars") or ob.get(key) or []
        out = []
        for p, q in rows:
            price = to_float(p)
            if price is None:
                continue
            out.append((price / 100 if price > 1 else price, to_float(q, 0.0)))
        return out
    yes_bids, no_bids = levels("yes"), levels("no")

    def depth(bids):   # buying YES takes NO bids (YES ask = 1 - NO bid), and vice versa
        if not bids:
            return 0.0, None
        best = max(p for p, _ in bids)
        return sum(q for p, q in bids if p >= best - within), round(1 - best, 2)
    yes_qty, yes_ask = depth(no_bids)
    no_qty, no_ask = depth(yes_bids)
    return {"ticker": ticker, "yes_ask": yes_ask, "yes_qty": yes_qty, "no_ask": no_ask, "no_qty": no_qty}


def _stat(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": round(statistics.fmean(xs), 4), "median": round(statistics.median(xs), 4)}


def run(kalshi: KalshiClient, journal: Journal, root: Path, days: float = 14, say=print,
        nws: NWSClient | None = None, observations=None, now: datetime | None = None) -> int:
    now = now or utcnow()
    observations = observations or iem_observations
    try:
        series = sorted(r["series"] for r in json.load(open(root / "data" / "niche_survey.json"))["series"]
                        if r["series"].startswith(("KXHIGH", "KXLOWT")) and r["series"] != "KXHIGHINFLATION")
    except (OSError, ValueError, KeyError):
        series = [s for s in temp_series(kalshi) if s != "KXHIGHINFLATION"]
    lo_ts, hi_ts = int((now - timedelta(days=days)).timestamp()), int((now - timedelta(hours=1)).timestamp())
    nws, stations, obs_cache = nws or NWSClient(), {}, {}
    events, locks, hour_err, jumps, depths = [], [], defaultdict(list), defaultdict(list), []
    say(f"Temperature survey: {len(series)} series, {days:g} days")
    for s in series:
      try:
          kind = kind_of(s)
          ms = [m for m in kalshi.iter_markets(max_markets=2000, series_ticker=s, status="settled",
                                               min_close_ts=lo_ts, max_close_ts=hi_ts)
                if m.get("result") in ("yes", "no") and bracket(m)]
          if not ms:
              continue
          code = cli_station(ms[0])
          if code not in stations:
              try:
                  stations[code] = nws.station(f"K{code}")
              except NWSError:
                  stations[code] = None
          st = stations[code]
          if st is None:
              say(f"  {s}: no station for CLI{code}, skipped")
              continue
          if code not in obs_cache:
              try:
                  obs_cache[code] = observations(code, now - timedelta(days=days + 3), now + timedelta(days=1))
              except requests.RequestException as e:
                  say(f"  {s}: no observations ({e})")
                  obs_cache[code] = []
          all_obs = obs_cache[code]
          by_event = defaultdict(list)
          for m in ms:
              by_event[m["event_ticker"]].append(m)
          n_locks = 0
          for ev, group in by_event.items():
              day = event_day(ev)
              if not day:
                  continue
              d0, d1 = climate_day_bounds(day, st.tz)
              obs = [(t, v) for t, v in all_obs if d0 <= t < d1]
              winner = next((m for m in group if m["result"] == "yes"), None)
              extreme = (max(v for _, v in obs) if kind == "high" else min(v for _, v in obs)) if obs else None
              wb = bracket(winner) if winner else None
              events.append({"series": s, "kind": kind, "day": day.isoformat(), "station": f"K{code}", "obs": len(obs),
                             "obs_extreme": None if extreme is None else round(extreme),
                             "official": wb, "volume": round(sum(to_float(m.get("volume_fp"), 0.0) for m in group))})
              for m in group:
                  br = bracket(m)
                  close, opened = parse_time(m.get("close_time")), parse_time(m.get("open_time"))
                  if not close or not opened:
                      continue
                  s_ts, e_ts = int(opened.timestamp()) // 60 * 60, int(close.timestamp()) // 60 * 60
                  try:
                      candles = kalshi.request("GET", f"/series/{s}/markets/{m['ticker']}/candlesticks",
                                               params={"start_ts": s_ts, "end_ts": e_ts, "period_interval": 1}
                                               ).get("candlesticks") or []
                  except KalshiError:
                      continue
                  track = raw_track(candles, s_ts, e_ts)
                  y = 1.0 if m["result"] == "yes" else 0.0
                  # accuracy by local (standard) hour of the day being measured
                  for h in HOURS:
                      i = int((d0 + timedelta(hours=h)).timestamp() - s_ts) // 60
                      if 0 <= i < len(track):
                          b, a, _ = track[i]
                          if b is not None and a is not None and 0 < b < a < 1 and a - b <= 0.10:
                              hour_err[(kind, h)].append(((a + b) / 2 - y) ** 2)
                  for j in analyse(quote_track(candles, s_ts, e_ts), m["result"])["jumps"]:
                      jumps[kind].append(j)
                  # the key test: once the station's own readings decided this bracket
                  for margin in (0, 1):
                      hit = lock(kind, br, obs, margin)
                      if not hit:
                          continue
                      t_obs, side = hit
                      i = int((t_obs + timedelta(minutes=LATENCY_MIN)).timestamp() - s_ts) // 60
                      if not (0 <= i < len(track)):
                          continue
                      cost = side_cost(track[i], side)
                      before = side_cost(track[i - 30], side) if i >= 30 else None
                      j = i
                      while j < len(track) and side_cost(track[j], side) < CAUGHT_UP:
                          j += 1
                      locks.append({"series": s, "kind": kind, "ticker": m["ticker"], "margin": margin, "side": side,
                                    "correct": side == m["result"], "obs_time": iso(t_obs),
                                    "local_hour": round((t_obs - d0).total_seconds() / 3600, 1),
                                    "cost": round(cost, 3), "cost_30min_before": None if before is None else round(before, 3),
                                    "profit": round(1 - cost - fee_per_contract(cost), 4) if cost < 1 else 0.0,
                                    "minutes_to_catch_up": j - i, "caught_up_before_close": j < len(track),
                                    "volume_while_cheap": round(sum(q[2] for q in track[i:j])),
                                    "market_volume": round(to_float(m.get("volume_fp"), 0.0))})
                      n_locks += margin == 1
          # how deep is the book right now on this city's busiest open markets?
          open_ms = sorted(kalshi.iter_markets(max_markets=50, series_ticker=s, status="open"),
                           key=lambda m: -to_float(m.get("volume_24h_fp"), 0.0))[:2]
          for m in open_ms:
              d = orderbook_depth(kalshi, m["ticker"])
              if d:
                  depths.append({"series": s, "kind": kind, **d})
          say(f"  {s}: {len(by_event)} days, {len(ms)} markets, {n_locks} brackets decided early by station data")
      except Exception as e:      # one bad city never sinks the whole survey
        say(f"  {s}: skipped after an error: {type(e).__name__}: {str(e)[:200]}")

    data = {"generated": iso(now), "days": days, "events": events, "locks": locks, "depth": depths,
            "hour_error": {f"{k}@{h}": _stat(v) for (k, h), v in sorted(hour_err.items())},
            "jumps": {k: {"n": len(v), "d5": _stat([j["d5"] for j in v]), "d30": _stat([j["d30"] for j in v]),
                          "d60": _stat([j["d60"] for j in v]), "follow": _stat([j["follow"] for j in v]),
                          "fade": _stat([j["fade"] for j in v])} for k, v in jumps.items()}}
    (root / "data" / "temp_survey.json").write_text(json.dumps(data, separators=(",", ":")) + "\n")
    text = report_markdown(data)
    (root / "TEMPS.md").write_text(text)
    say(text[:4000])
    return 0


def _c(x):
    return "–" if x is None else f"{x * 100:+.1f}¢"


def summarize_locks(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["correct"]]
    cheap = [r for r in ok if r["cost"] <= 0.95]
    return {"n": len(rows), "correct": len(ok), "correct_pct": round(100 * len(ok) / len(rows), 1) if rows else None,
            "already_priced_pct": round(100 * sum(r["cost"] >= CAUGHT_UP for r in ok) / len(ok), 1) if ok else None,
            "cheap": len(cheap), "cheap_pct": round(100 * len(cheap) / len(ok), 1) if ok else None,
            "profit_all": _stat([(1 - r["cost"] - fee_per_contract(r["cost"])) if r["correct"]
                                 else -(r["cost"] + fee_per_contract(r["cost"])) for r in rows if r["cost"] <= 0.95]),
            "cost_cheap": _stat([r["cost"] for r in cheap]),
            "catch_up_min": _stat([r["minutes_to_catch_up"] for r in cheap]),
            "volume_while_cheap": _stat([r["volume_while_cheap"] for r in cheap])}


def report_markdown(data: dict) -> str:
    ev, locks = data["events"], data["locks"]
    lines = ["# Daily high / low temperature markets: deep survey", "",
             f"*{len(ev)} city-days over the last {data['days']:g} days ({data['generated'][:16].replace('T', ' ')} UTC), "
             f"{sum(e['volume'] for e in ev):,} contracts traded. Station readings: NWS hourly and special reports via the "
             "Iowa Environmental Mesonet archive, the same reports a live watcher would see. Read-only research; not "
             "financial advice.*", ""]
    # 1) station data vs how the markets settled
    lines += ["## Do station readings match the official numbers?", "",
              "Official = the winning bracket. Readings are hourly and special reports, so the official high can be a bit "
              "higher (and the low a bit lower) than any single reading.", "",
              "| | City-days | Reading inside winning bracket | Off by 1° | Off by 2°+ |", "|---|---|---|---|---|"]
    for kind in ("high", "low"):
        rows = [e for e in ev if e["kind"] == kind and e["official"] and e["obs_extreme"] is not None]
        def off(e):
            lo, hi = e["official"]
            x = e["obs_extreme"]
            if (lo is None or x >= lo) and (hi is None or x <= hi):
                return 0
            return (lo - x) if lo is not None and x < lo else (x - hi)
        d = [off(e) for e in rows]
        lines.append(f"| {kind.title()}s | {len(rows)} | {sum(x == 0 for x in d)} | {sum(x == 1 for x in d)} | {sum(x >= 2 for x in d)} |")
    # 2) the key test
    lines += ["", "## Once the station had already decided a bracket, was the market still behind?", "",
              "A reading of 70° means today's high can't be in '67°–68°' (NO) and '69° or above' is YES, hours before the "
              "day ends. *Strict* uses the reading as is; *safe* demands one extra degree. *Correct* = the market settled "
              "the way the reading said. *Already priced* = the decided side already cost 97¢+ five minutes after the "
              "reading. *Cheap* = it still cost 95¢ or less. *Profit* = average per $1 contract buying the decided side "
              "then, after fees, counting wrong calls as losses.", "",
              "| | Rule | Decided early | Correct | Already priced | Still cheap | Avg price when cheap | Profit per $1 | Minutes to catch up (median) | Contracts traded meanwhile (median) |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for kind in ("high", "low"):
        for margin, label in ((0, "strict"), (1, "safe")):
            s = summarize_locks([r for r in locks if r["kind"] == kind and r["margin"] == margin])
            if not s["n"]:
                continue
            lines.append(f"| {kind.title()}s | {label} | {s['n']} | {s['correct_pct']}% | {s['already_priced_pct']}% | "
                         f"{s['cheap']} ({s['cheap_pct']}%) | {_fmt(s['cost_cheap'].get('mean'), '{:.2f}')} | "
                         f"{_c(s['profit_all'].get('mean'))} (n={s['profit_all']['n']}) | {_fmt(s['catch_up_min'].get('median'), '{:.0f}')} | "
                         f"{_fmt(s['volume_while_cheap'].get('median'), '{:,.0f}')} |")
    # 3) by city (safe rule)
    lines += ["", "## By city (safe rule)", "",
              "| Market | Decided early | Correct | Still cheap | Profit per $1 | Minutes to catch up | Avg contracts per city-day |",
              "|---|---|---|---|---|---|---|"]
    per = defaultdict(list)
    for r in locks:
        if r["margin"] == 1:
            per[r["series"]].append(r)
    vol = defaultdict(list)
    for e in ev:
        vol[e["series"]].append(e["volume"])
    for s_, rows in sorted(per.items(), key=lambda kv: -(summarize_locks(kv[1])["profit_all"].get("mean") or -9)):
        s = summarize_locks(rows)
        lines.append(f"| `{s_}` | {s['n']} | {s['correct_pct']}% | {s['cheap']} | {_c(s['profit_all'].get('mean'))} | "
                     f"{_fmt(s['catch_up_min'].get('median'), '{:.0f}')} | {_fmt(statistics.fmean(vol[s_]) if vol[s_] else None, '{:,.0f}')} |")
    # 4) accuracy by hour, jumps, depth
    lines += ["", "## How accurate were prices through the day?", "",
              "Average squared gap between each bracket's price and its result, at local (standard) time on the day "
              "being measured. 0 = perfect.", "", "| | " + " | ".join(f"{h}:00" for h in HOURS) + " |",
              "|---|" + "---|" * len(HOURS)]
    for kind in ("high", "low"):
        cells = [_fmt(data["hour_error"].get(f"{kind}@{h}", {}).get("mean"), "{:.3f}") for h in HOURS]
        lines.append(f"| {kind.title()}s | " + " | ".join(cells) + " |")
    lines += ["", "## After sudden 10¢ price jumps", "", "| | Jumps | Drift 5 min | Drift 30 min | Drift 60 min | Follow | Fade |",
              "|---|---|---|---|---|---|---|"]
    for kind, j in sorted(data["jumps"].items()):
        lines.append(f"| {kind.title()}s | {j['n']} | {_c(j['d5'].get('mean'))} | {_c(j['d30'].get('mean'))} | "
                     f"{_c(j['d60'].get('mean'))} | {_c(j['follow'].get('mean'))} | {_c(j['fade'].get('mean'))} |")
    dep = data["depth"]
    if dep:
        lines += ["", "## Contracts on offer right now (within 3¢ of the best price, busiest open brackets)", "",
                  "| | Brackets checked | Median YES contracts | Median NO contracts |", "|---|---|---|---|"]
        for kind in ("high", "low"):
            d = [x for x in dep if x["kind"] == kind]
            if d:
                lines.append(f"| {kind.title()}s | {len(d)} | {statistics.median(x['yes_qty'] for x in d):,.0f} | "
                             f"{statistics.median(x['no_qty'] for x in d):,.0f} |")
    lines.append("")
    return "\n".join(lines)


def _fmt(x, f="{:.1f}"):
    return "–" if x is None else f.format(x)
