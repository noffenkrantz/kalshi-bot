"""Offline test for the market survey: a fake Kalshi with one slow and one busy market type."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.journal import Journal
from bot.survey import report_markdown, survey, tradable

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


def mk(ticker, event, status, result="", vol=5000, bid=0.40, ask=0.42, size=300, close_h=-5):
    return {"ticker": ticker, "event_ticker": event, "result": result, "volume_fp": f"{vol:.2f}",
            "volume_24h_fp": "800.00", "yes_bid_dollars": f"{bid:.4f}", "yes_ask_dollars": f"{ask:.4f}",
            "yes_bid_size_fp": f"{size:.2f}", "yes_ask_size_fp": f"{size:.2f}",
            "open_time": (NOW - timedelta(days=3)).isoformat(),
            "close_time": (NOW + timedelta(hours=close_h)).isoformat(), "title": ticker}


class FakeKalshi:
    def __init__(self):
        self.open = [mk("KXGASMI-26NOV26-T3", "KXGASMI-26NOV26", "open", close_h=20),
                     mk("KXNBA-G9-A", "KXNBA-G9", "open", bid=0.30, ask=0.50, size=5, close_h=3)]
        self.settled = [mk(f"KXGASMI-26NOV2{d}-T3", f"KXGASMI-26NOV2{d}", "settled", result="yes") for d in (2, 3, 4)]
        self.settled += [mk(f"KXNBA-G{i}-A", f"KXNBA-G{i}", "settled", result="no") for i in range(3)]

    def iter_markets(self, max_markets=1000, **p):
        yield from (self.open if p["status"] == "open" else self.settled)

    def get_series(self, s):
        return {"category": "Economics" if s == "KXGASMI" else "Sports", "title": f"{s} name"}

    def request(self, method, path, params=None):
        start, end = params["start_ts"], params["end_ts"]
        if "KXGASMI" in path:      # quote changes twice a day; drifts to the result late
            pts = {0: (0.60, 0.62), 600: (0.80, 0.82), 1200: (0.95, 0.97)}
        else:                      # changes every minute
            pts = {i: (0.40 + 0.01 * (i % 5), 0.42 + 0.01 * (i % 5)) for i in range(0, (end - start) // 60)}
        return {"candlesticks": [{"end_period_ts": start + 60 * i, "volume_fp": "3.00",
                                  "yes_bid": {"close_dollars": f"{b:.4f}"}, "yes_ask": {"close_dollars": f"{a:.4f}"}}
                                 for i, (b, a) in pts.items()]}


def test_survey_measures_speed_tradability_and_accuracy(tmp_path):
    data = survey(FakeKalshi(), Journal(tmp_path / "data"), now=NOW, days=3, say=lambda *_: None)
    rows = {r["series"]: r for r in data["series"]}
    gas, nba = rows["KXGASMI"], rows["KXNBA"]
    assert gas["category"] == "Economics" and gas["sampled"] == 3 and nba["sampled"] == 2   # fast types get fewer
    assert gas["quote_changes_per_hour"] < 1 < nba["quote_changes_per_hour"]
    assert tradable(gas) and not tradable(nba)                    # NBA: 20c spread, 5 contracts on offer
    assert gas["err_6h"] is not None and gas["late_1h"] > 0       # favourite (YES) was still cheap an hour out
    text = report_markdown(data)
    assert "KXGASMI" in text.split("## Where prices")[0] and "KXNBA" not in text.split("## Where prices")[0]
