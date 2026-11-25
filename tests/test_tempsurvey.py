"""Offline test for the temperature survey: one NYC high-temperature day where the station hit 70°
at 3:51 PM, deciding three brackets while one of them was still cheap on Kalshi."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from bot.journal import Journal
from bot.nws import Station
from bot.tempsurvey import bracket, lock, run, summarize_locks

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
OPEN = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)
CLOSE = datetime(2026, 11, 24, 6, 0, tzinfo=timezone.utc)
RULE = "If the maximum temperature recorded at Central Park, New York (CLINYC) for Nov 23, 2026, is ..."


def mk(ticker, strike_type, result, floor=None, cap=None):
    return {"ticker": ticker, "event_ticker": "KXHIGHNY-26NOV23", "result": result, "strike_type": strike_type,
            "floor_strike": floor, "cap_strike": cap, "rules_primary": RULE, "volume_fp": "1000.00",
            "volume_24h_fp": "100.00", "open_time": OPEN.isoformat(), "close_time": CLOSE.isoformat()}


# minute (from the market's open) -> (yes_bid, yes_ask, volume)
TRACKS = {
    "KXHIGHNY-26NOV23-T60": {0: (0.01, 0.02, 5)},                                     # NO already ~certain
    "KXHIGHNY-26NOV23-B67.5": {0: (0.30, 0.33, 5), 1830: (0.01, 0.03, 40)},           # NO cheap for 34 min
    "KXHIGHNY-26NOV23-T68": {0: (0.55, 0.60, 3), 1800: (0.55, 0.60, 50), 1850: (0.97, 0.99, 80)},
}


class FakeKalshi:
    settled = [mk("KXHIGHNY-26NOV23-T60", "less", "no", cap=61), mk("KXHIGHNY-26NOV23-B67.5", "between", "no", 67, 68),
               mk("KXHIGHNY-26NOV23-T68", "greater", "yes", floor=68)]

    def iter_markets(self, max_markets=1000, **p):
        assert p["series_ticker"] == "KXHIGHNY"
        yield from (self.settled if p["status"] == "settled" else [dict(self.settled[0], ticker="KXHIGHNY-26NOV26-T60", yes_ask_dollars="0.4200")])

    def request(self, method, path, params=None):
        if path.endswith("/orderbook"):
            return {"orderbook_fp": {"yes_dollars": [["0.4000", "200.00"]], "no_dollars": [["0.5800", "150.00"]]}}
        ticker = path.split("/")[-2]
        return {"candlesticks": [{"end_period_ts": params["start_ts"] + 60 * i, "volume_fp": f"{v:.2f}",
                                  "yes_bid": {"close_dollars": f"{b:.4f}"}, "yes_ask": {"close_dollars": f"{a:.4f}"}}
                                 for i, (b, a, v) in TRACKS[ticker].items()]}


class FakeNWS:
    def station(self, sid):
        assert sid == "KNYC"
        return Station("KNYC", "New York City, Central Park", "America/New_York", 40.78, -73.97)


def fake_obs(code, start, end):
    assert code == "NYC"
    day = datetime(2026, 11, 23, tzinfo=timezone.utc)
    return [(day + timedelta(hours=12, minutes=51), 50.0), (day + timedelta(hours=19, minutes=51), 64.0),
            (day + timedelta(hours=20, minutes=51), 70.0),
            (day + timedelta(days=1, hours=6), 30.0)]          # after the climate day: ignored


def test_bracket_and_lock_rules():
    assert bracket({"strike_type": "greater", "floor_strike": 68}) == (69, None)
    assert bracket({"strike_type": "less", "cap_strike": 61}) == (None, 60)
    assert bracket({"strike_type": "between", "floor_strike": 67, "cap_strike": 68}) == (67, 68)
    t = [(NOW, 68.4), (NOW + timedelta(hours=1), 69.0)]
    assert lock("high", (69, None), t, 0)[1] == "yes" and lock("high", (69, None), t, 1) is None
    assert lock("high", (67, 68), t, 0) == (NOW + timedelta(hours=1), "no")
    assert lock("low", (None, 40), [(NOW, 40.6)], 0) is None and lock("low", (None, 40), [(NOW, 40.0)], 0)[1] == "yes"
    assert lock("low", (45, 46), [(NOW, 44.0)], 0)[1] == "no"


def test_survey_finds_brackets_still_cheap_after_the_station_decided_them(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "niche_survey.json").write_text(json.dumps({"series": [{"series": "KXHIGHNY"},
                                                                                {"series": "KXHIGHINFLATION"}]}))
    run(FakeKalshi(), Journal(tmp_path / "data"), tmp_path, days=14, say=lambda *_: None,
        nws=FakeNWS(), observations=fake_obs, now=NOW)
    data = json.loads((tmp_path / "data" / "temp_survey.json").read_text())
    (ev,) = data["events"]
    assert ev["obs_extreme"] == 70 and ev["official"] == [69, None] and ev["obs"] == 3
    strict = {r["ticker"]: r for r in data["locks"] if r["margin"] == 0}
    top, mid, low = strict["KXHIGHNY-26NOV23-T68"], strict["KXHIGHNY-26NOV23-B67.5"], strict["KXHIGHNY-26NOV23-T60"]
    assert top["side"] == "yes" and top["correct"] and top["cost"] == 0.60 and top["minutes_to_catch_up"] == 54
    assert top["volume_while_cheap"] == 50 and 15.8 <= top["local_hour"] <= 15.9
    assert mid["side"] == "no" and mid["cost"] == 0.70 and mid["minutes_to_catch_up"] == 34
    assert low["side"] == "no" and low["cost"] == 0.99           # was decided at 2:51 PM and already priced
    s = summarize_locks([r for r in data["locks"] if r["margin"] == 0])
    assert s["n"] == 3 and s["correct_pct"] == 100.0 and s["cheap"] == 2
    assert 0.3 < s["profit_all"]["mean"] < 0.4
    assert data["depth"][0]["yes_ask"] == 0.42 and data["depth"][0]["yes_qty"] == 150
    text = (tmp_path / "TEMPS.md").read_text()
    assert "| Highs | strict | 3 | 100.0% |" in text and "KXHIGHNY" in text


def test_bottom_line_says_whether_there_is_a_lag():
    from bot.tempsurvey import bottom_line
    priced = {"margin": 0, "correct": True, "cost": 1.0, "cost_30min_before": 0.6}
    cheap = {"margin": 0, "correct": True, "cost": 0.6, "cost_30min_before": 0.6}
    assert "no lag" in " ".join(bottom_line({"locks": [priced] * 50}))
    assert "tradable edge" in " ".join(bottom_line({"locks": [cheap] * 10 + [priced] * 10}))
