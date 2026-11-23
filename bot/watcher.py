"""Data watcher: compares official weather readings with live Kalshi prices.

`python -m bot watch --inspect` prints what the live data looks like (no trades, no files).
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta

from .kalshi import KalshiClient, KalshiError
from .nws import NWSClient, NWSError
from .util import utcnow


def inspect(kalshi: KalshiClient, nws: NWSClient, say=print) -> None:
    now = utcnow()
    say(f"# Watcher inspect, {now:%Y-%m-%d %H:%M} UTC\n")
    rain_events, samples = Counter(), {}
    for m in kalshi.iter_markets(max_markets=20000, status="open", mve_filter="exclude"):
        key = f"{m.get('series_ticker') or ''} {m.get('event_ticker') or ''} {m.get('title') or ''}"
        if "RAIN" in key.upper():
            rain_events[m.get("event_ticker")] += 1
            samples.setdefault(m.get("event_ticker"), m)
    say(f"Open events with RAIN in the name: {len(rain_events)}")
    for ev, n in rain_events.most_common(40):
        m = samples[ev]
        say(f"  {ev}: {n} markets, e.g. {m.get('ticker')} | {m.get('title')} | {m.get('yes_sub_title')} "
            f"| closes {m.get('close_time')}")

    series = sorted({(samples[ev].get("series_ticker") or ev.split("-")[0]) for ev in rain_events})
    say(f"\nSeries: {series}")
    for s in series[:6]:
        try:
            info = kalshi.get_series(s)
            say(f"\n## series {s}\n" + json.dumps({k: info.get(k) for k in (
                "title", "frequency", "category", "settlement_sources", "contract_url", "tags")}, indent=1)[:1500])
        except KalshiError as e:
            say(f"series {s}: {e}")

    # Full detail for a few markets of the biggest daily rain event
    for ev, _ in rain_events.most_common(3):
        try:
            markets = list(kalshi.iter_markets(max_markets=50, event_ticker=ev, status="open"))
        except KalshiError as e:
            say(f"{ev}: {e}")
            continue
        say(f"\n## event {ev}: {len(markets)} open markets")
        for m in markets[:3]:
            keep = {k: m.get(k) for k in (
                "ticker", "title", "subtitle", "yes_sub_title", "no_sub_title", "status", "open_time",
                "close_time", "expected_expiration_time", "expiration_time", "latest_expiration_time",
                "occurrence_datetime", "strike_type", "floor_strike", "cap_strike", "custom_strike",
                "yes_bid_dollars", "yes_ask_dollars", "volume_24h_fp", "can_close_early", "rules_primary",
                "rules_secondary", "settlement_timer_seconds")}
            say(json.dumps(keep, indent=1)[:2500])
        say("  all tickers: " + ", ".join(m["ticker"] for m in markets))

    # One weather station end to end
    for sid in ("KNYC", "KPHL"):
        try:
            st = nws.station(sid)
            say(f"\n## NWS station {sid}: {st}")
            obs = nws.observations(sid, now - timedelta(hours=8))
            say(f"{len(obs)} observations in the last 8h; last 6:")
            for o in obs[-6:]:
                say(f"  {o.time:%m-%d %H:%M}Z {o.report_type} precip={o.precip_in} | {o.raw}")
            wet = [o for o in obs if o.precip_in]
            say(f"  reports with measurable rain: {len(wet)}")
            pops = nws.hourly_pop(sid)
            say("  next 6 hourly chances of rain: " + ", ".join(f"{s:%H}Z {p:.0%}" for s, _, p in pops[:6]))
        except NWSError as e:
            say(f"{sid}: {e}")
