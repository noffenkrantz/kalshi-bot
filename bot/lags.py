"""Lag scanner: where do Kalshi prices respond slowly to new information?

`python -m bot lags --probe` prints the shape of Kalshi's price-history data (read-only).
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta

from .kalshi import KalshiClient, KalshiError
from .util import utcnow


def probe(kalshi: KalshiClient, say=print) -> None:
    now = utcnow()
    say(f"# Lag scanner probe, {now:%Y-%m-%d %H:%M} UTC")
    lo, hi = int((now - timedelta(hours=24)).timestamp()), int(now.timestamp())
    settled, seen = [], 0
    try:
        for m in kalshi.iter_markets(max_markets=20000, status="settled", min_close_ts=lo, max_close_ts=hi,
                                     mve_filter="exclude"):
            seen += 1
            settled.append(m)
    except KalshiError as e:
        say(f"settled listing failed: {e}")
    say(f"settled in the last 24h (no combos): {seen}")
    series = Counter((m.get("event_ticker") or "").split("-")[0] for m in settled)
    say(f"distinct series: {len(series)}; top 25: {series.most_common(25)}")
    vols = sorted((float(m.get("volume_fp") or m.get("volume") or 0) for m in settled), reverse=True)
    say(f"volume quantiles (top/10th/50th/100th/500th): "
        f"{[vols[i] for i in (0, 9, 49, 99, 499) if i < len(vols)]}")
    if not settled:
        return
    top = sorted(settled, key=lambda m: float(m.get("volume_fp") or m.get("volume") or 0), reverse=True)
    m = top[min(20, len(top) - 1)]
    keys = sorted(m.keys())
    say(f"\nmarket keys: {keys}")
    say(json.dumps({k: m.get(k) for k in keys if k not in ("rules_primary", "rules_secondary")}, indent=1)[:3000])
    ticker = m["ticker"]
    series_ticker = m.get("series_ticker") or m["event_ticker"].split("-")[0]
    close = int(now.timestamp())
    for k in ("close_time", "settlement_ts"):
        pass
    try:
        from .util import parse_time
        ct = parse_time(m.get("close_time"))
        close = int(ct.timestamp()) if ct else close
    except Exception:
        pass
    for period, hours in ((1, 24), (1, 72), (60, 72)):
        try:
            d = kalshi.request("GET", f"/series/{series_ticker}/markets/{ticker}/candlesticks",
                               params={"start_ts": close - hours * 3600, "end_ts": close, "period_interval": period})
            cs = d.get("candlesticks") or []
            say(f"\ncandles period={period} over {hours}h: {len(cs)} candles; top-level keys {sorted(d.keys())}")
            if cs:
                say(json.dumps(cs[len(cs) // 2], indent=1)[:2000])
        except KalshiError as e:
            say(f"candles period={period} {hours}h: {e}")
    try:
        d = kalshi.request("GET", "/markets/trades", params={"ticker": ticker, "limit": 5})
        say(f"\ntrades keys {sorted(d.keys())}; sample: {json.dumps((d.get('trades') or [])[:2], indent=1)[:1200]}")
    except KalshiError as e:
        say(f"trades: {e}")
    ev = m.get("event_ticker")
    try:
        e = kalshi.get_event(ev)
        s = kalshi.get_series(series_ticker)
        say(f"\nevent category: {e.get('category')}; series category: {s.get('category')}; series title: {s.get('title')}")
    except KalshiError as e:
        say(f"event/series: {e}")
