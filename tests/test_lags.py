"""Offline tests for the lag scanner: synthetic price histories, fake Kalshi."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.journal import Journal
from bot.lags import (analyse, pick_markets, quote_track, report_markdown, scan, summarize, verdict)

NOW = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)


def candles_from(mids: dict[int, float], start_ts: int, spread: float = 0.02) -> list[dict]:
    """{minute: mid} -> Kalshi-style 1-minute candles (only minutes that changed)."""
    out = []
    for i, m in sorted(mids.items()):
        out.append({"end_period_ts": start_ts + 60 * i,
                    "yes_bid": {"close_dollars": f"{m - spread / 2:.4f}"},
                    "yes_ask": {"close_dollars": f"{m + spread / 2:.4f}"}})
    return out


def slow_market_track(start_ts=0, minutes=600, jump_at=200):
    mids = {0: 0.40}
    for k in range(1, 6):
        mids[jump_at - 5 + k] = 0.40 + 0.03 * k          # 0.40 -> 0.55 in 5 minutes
    for k in range(1, 31):
        mids[jump_at + k] = 0.55 + 0.004 * k             # keeps drifting to 0.67 over 30 minutes
    return quote_track(candles_from(mids, start_ts), start_ts, start_ts + 60 * minutes)


def test_quote_track_fills_gaps_and_drops_bad_quotes():
    t = quote_track(candles_from({0: 0.5, 3: 0.6}, 0) + [
        {"end_period_ts": 600, "yes_bid": {"close_dollars": "0.10"}, "yes_ask": {"close_dollars": "0.40"}}], 0, 900)
    assert t[1] == t[0] and t[3][0] == 0.59
    assert t[10] is None and t[12] is None                 # 30-cent spread: unusable
    long = quote_track(candles_from({0: 0.5}, 0), 0, 13 * 3600)
    assert long[12 * 60] is not None and long[12 * 60 + 1] is None   # a quote is carried for 12 hours


def test_analyse_finds_jump_drift_and_follow_profit():
    a = analyse(slow_market_track(), "yes")
    assert len(a["jumps"]) == 1
    j = a["jumps"][0]
    # spotted as soon as the move reaches 10 cents within 5 minutes (0.40 -> 0.52), as a trader would
    assert j["from"] == 0.40 and j["to"] == 0.52
    assert 0.04 < j["d5"] < 0.05 and 0.14 < j["d30"] < 0.15
    # buy YES one minute later at the ask (0.56) plus fee, and YES wins
    assert 0.42 < j["follow"] < 0.43 and -0.48 < j["fade"] < -0.47
    assert a["late"]["1h"]["fav_price"] > 0.6 and a["late"]["1h"]["upset"] is False


def test_no_jump_for_slow_moves_and_one_per_half_hour():
    calm = quote_track(candles_from({i: 0.40 + 0.001 * i for i in range(300)}, 0), 0, 300 * 60)
    assert analyse(calm, "no")["jumps"] == []
    choppy = {}
    for i in range(0, 300):
        choppy[i] = 0.30 if (i // 10) % 2 == 0 else 0.45     # swings every 10 minutes
    a = analyse(quote_track(candles_from(choppy, 0), 0, 300 * 60), "no")
    gaps = [b["min_before_close"] - c["min_before_close"] for b, c in zip(a["jumps"], a["jumps"][1:])]
    assert 1 < len(a["jumps"]) <= 5 and all(g >= 30 for g in gaps)


def m(ticker, event, vol, result="yes"):
    return {"ticker": ticker, "event_ticker": event, "volume_fp": f"{vol:.2f}", "result": result,
            "open_time": (NOW - timedelta(days=2)).isoformat(), "close_time": (NOW - timedelta(hours=2)).isoformat(),
            "title": ticker}


def test_pick_markets_spreads_across_categories_events_and_series():
    ms = [m(f"KXNBA-G{i}-A", f"KXNBA-G{i}", 10_000_000 - i) for i in range(10)]
    ms += [m(f"KXNBA-G0-B", "KXNBA-G0", 9_999_999)]               # same event as G0-A
    ms += [m("KXCPI-26NOV-T3", "KXCPI-26NOV", 5_000), m("KXCPI-26NOV-T4", "KXCPI-26NOV", 4_000),
           m("KXTINY-1-A", "KXTINY-1", 10)]                        # too little volume
    cats = {"KXNBA": "Sports", "KXCPI": "Economics", "KXTINY": "Economics"}
    picked = [p["ticker"] for p in pick_markets(ms, cats, per_category=5, per_series=3)]
    assert picked.count("KXNBA-G0-B") == 0
    assert sum(t.startswith("KXNBA") for t in picked) == 3
    assert "KXCPI-26NOV-T3" in picked and "KXCPI-26NOV-T4" not in picked and "KXTINY-1-A" not in picked


class FakeKalshi:
    def __init__(self, markets, tracks):
        self.markets, self.tracks, self.calls = markets, tracks, []

    def iter_markets(self, max_markets=1000, **params):
        assert params["status"] == "settled" and params["mve_filter"] == "exclude"
        yield from self.markets

    def get_series(self, s):
        return {"category": "Economics" if s == "KXCPI" else "Sports", "title": f"{s} title"}

    def request(self, method, path, params=None):
        self.calls.append(path)
        ticker = path.split("/markets/")[1].split("/")[0]
        start = params["start_ts"]
        return {"candlesticks": self.tracks[ticker](start)}


def test_scan_then_summary_and_report(tmp_path):
    ms = [m("KXCPI-26NOV-T3", "KXCPI-26NOV", 50_000), m("KXNBA-G1-A", "KXNBA-G1", 900_000, result="no")]

    def jumpy(start):
        mids = {0: 0.40}
        for k in range(1, 6):
            mids[2000 + k] = 0.40 + 0.03 * k
        for k in range(1, 31):
            mids[2005 + k] = 0.55 + 0.004 * k
        return candles_from(mids, start)
    kalshi = FakeKalshi(ms, {"KXCPI-26NOV-T3": jumpy, "KXNBA-G1-A": lambda s: candles_from({0: 0.3}, s)})
    j = Journal(tmp_path / "data")
    lines = []
    assert scan(kalshi, j, now=NOW, say=lines.append) == 2
    rows = Journal(tmp_path / "data").rows["lag_scan"]
    assert {r["category"] for r in rows} == {"Economics", "Sports"}
    cpi = next(r for r in rows if r["series"] == "KXCPI")
    assert len(cpi["jumps"]) == 1 and cpi["jumps"][0]["follow"] > 0.4
    assert "2 across 2 categories" in lines[-1].replace("scanned ", "")
    # Second scan: nothing settled since, nothing rescanned.
    assert scan(kalshi, Journal(tmp_path / "data"), now=NOW + timedelta(minutes=10), say=lines.append) == 0

    s = summarize(rows)
    assert s["markets"] == 2 and s["jumps"] == 1
    econ = next(c for c in s["categories"] if c["name"] == "Economics")
    assert econ["follow"]["n"] == 1 and verdict(econ) == "early"
    text = report_markdown(s)
    assert "| Economics | 1 | 1 |" in text and "early" in text
    assert report_markdown(summarize([])).startswith("# Where Kalshi prices lag")


def test_verdicts():
    def group(follow, fade, d30, n=40):
        def st(v):
            return {"n": n, "mean": v, "se": 0.01}
        return {"follow": st(follow), "fade": st(fade), "d30": st(d30)}
    assert verdict(group(0.05, -0.08, 0.03)) == "lags"
    assert verdict(group(-0.05, 0.03, -0.01)) == "overreacts"
    assert verdict(group(-0.01, -0.05, 0.04)) == "drifts"
    assert verdict(group(0.005, -0.05, 0.005)) == "keeps up"
