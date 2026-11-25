"""Deep survey of Kalshi's daily high / low temperature markets.

    python -m bot tempsurvey --probe     what the markets' rules, brackets and times look like

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
