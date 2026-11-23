"""Offline tests for the rain watcher: fake Kalshi, fake weather service, fake clock."""
from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from bot.config import load_config
from bot.journal import Journal
from bot.nws import NWSError, Obs, Station, climate_day_bounds, metar_hourly_precip
from bot.postmortem import pending_reviews
from bot.watcher import (RainWatcher, cli_code, is_daily_rain_market, market_day, read_rain,
                         safe_window)

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)   # 1 PM in New York
DAY_START = datetime(2026, 11, 20, 5, 0, tzinfo=timezone.utc)


def rain_market(city="NYC", cli="NYC", yes_bid=0.55, yes_ask=0.60, day="26NOV20", size=5000):
    return {
        "ticker": f"KXRAIN-{day}-{city}", "event_ticker": f"KXRAIN-{day}", "series_ticker": "KXRAIN",
        "market_type": "binary", "title": f"Will it rain in {city} on Nov 20, 2026?",
        "strike_type": "greater", "floor_strike": 0, "cap_strike": None,
        "rules_primary": f"If the total precipitation at CLI{cli} in {city} in Nov 20, 2026 is strictly "
                         f"greater than 0 inches, then the market resolves to Yes.",
        "close_time": "2026-11-21T05:00:00Z",
        "yes_bid_dollars": f"{yes_bid:.4f}", "yes_ask_dollars": f"{yes_ask:.4f}",
        "yes_bid_size_fp": f"{size:.2f}", "yes_ask_size_fp": f"{size:.2f}", "volume_24h_fp": "7000.00",
    }


def metar(t: datetime, precip: str | None) -> Obs:
    raw = f"KNYC {t:%d%H%M}Z AUTO 05005KT 8SM -RA OVC060 14/13 A3000 RMK AO2" + (f" P{precip}" if precip else "")
    return Obs(t, raw, metar_hourly_precip(raw), "METAR")


class FakeKalshi:
    def __init__(self, markets):
        self.markets = {m["ticker"]: m for m in markets}

    def iter_markets(self, max_markets=1000, **params):
        assert params.get("series_ticker") == "KXRAIN" and params.get("status") == "open"
        yield from list(self.markets.values())


class FakeNWS:
    def __init__(self, obs):
        self.obs, self.calls = obs, 0

    def station(self, sid):
        if sid in ("KNYC", "KPBI"):
            return Station(sid, "Central Park" if sid == "KNYC" else "Palm Beach", "America/New_York", 40.78, -73.97)
        raise NWSError(f"GET /stations/{sid} -> HTTP 404")

    def observations(self, sid, start, end=None):
        self.calls += 1
        return [o for o in self.obs if o.time >= start]


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def make_root(tmp_path: Path) -> Path:
    shutil.copy(ROOT / "config.toml", tmp_path / "config.toml")
    (tmp_path / "data").mkdir()
    return tmp_path


def make_watcher(tmp_path, markets, obs, dry_run=False, clock=None):
    root = make_root(tmp_path)
    lines = []
    w = RainWatcher(load_config(root / "config.toml"), FakeKalshi(markets), FakeNWS(obs), root,
                    dry_run=dry_run, say=lines.append, clock=clock or Clock(NOW))
    return w, lines


# ---- parsing ---------------------------------------------------------------------------
def test_metar_precip_groups():
    assert metar_hourly_precip("KNYC 231451Z RMK AO2 SLP163 P0012 T01170083") == 0.12
    assert metar_hourly_precip("KNYC 231451Z RMK AO2 RAB49 P0000 T0144") == 0.0      # a trace
    assert metar_hourly_precip("KNYC 231451Z RMK AO2 SLP163") is None
    assert metar_hourly_precip("KNYC 231451Z RMK AO2 P////") is None
    assert metar_hourly_precip("KNYC 231451Z P0012") is None                          # not in remarks


def test_climate_day_and_safe_window():
    assert climate_day_bounds(date(2026, 11, 20), "America/New_York")[0] == DAY_START
    # Summer: NWS day is 1 AM-1 AM daylight time; calendar day is midnight-midnight. Use the overlap.
    s, e = safe_window(date(2026, 7, 4), "America/New_York")
    assert (s, e) == (datetime(2026, 7, 4, 5, tzinfo=timezone.utc), datetime(2026, 7, 5, 4, tzinfo=timezone.utc))
    assert safe_window(date(2026, 11, 20), "America/New_York") == (DAY_START, DAY_START + timedelta(days=1))


def test_market_recognition():
    m = rain_market(city="WPB", cli="DJT")
    assert market_day(m) == date(2026, 11, 20) and cli_code(m) == "DJT" and is_daily_rain_market(m)
    monthly = {**rain_market(), "event_ticker": "KXRAINBOSM-26NOV", "floor_strike": 10,
               "rules_primary": "If the total precipitation at CLIBOS in Boston in Nov 2026 is strictly "
                                "greater than 10 inches, then the market resolves to Yes."}
    assert not is_daily_rain_market(monthly)


def test_read_rain_only_counts_reports_wholly_inside_the_day():
    obs = [metar(DAY_START + timedelta(minutes=51), "0020"),   # covers 11:51 PM-12:51 AM: straddles midnight
           metar(DAY_START + timedelta(hours=2, minutes=51), "0000"),   # trace
           metar(DAY_START + timedelta(hours=9, minutes=51), None)]
    assert read_rain(obs, DAY_START, DAY_START + timedelta(days=1), "KNYC", NOW).rain_in == 0.0
    obs.append(metar(DAY_START + timedelta(hours=10, minutes=51), "0003"))
    obs.append(metar(DAY_START + timedelta(hours=11, minutes=51), "0004"))
    r = read_rain(obs, DAY_START, DAY_START + timedelta(days=1), "KNYC", NOW)
    assert r.rain_in == 0.07 and r.first_rain_at == DAY_START + timedelta(hours=10, minutes=51)


# ---- the watcher ------------------------------------------------------------------------
def test_dry_day_no_signal(tmp_path):
    w, _ = make_watcher(tmp_path, [rain_market()], [metar(NOW - timedelta(minutes=9), None)])
    w.tick()
    assert not w.signals and not w.journal.rows["watch_decisions"]


def test_rain_reported_makes_signal_bet_and_followups(tmp_path):
    clock = Clock(NOW)
    m = rain_market(yes_bid=0.55, yes_ask=0.60)
    w, lines = make_watcher(tmp_path, [m], [], clock=clock)
    w.tick()                                     # dry so far: records the 60c price
    w.nws.obs = [metar(NOW + timedelta(minutes=51), "0012")]
    clock.t = NOW + timedelta(minutes=56)
    w.station_next.clear()
    w.next_market_check = clock.t
    w.tick()
    sig = w.signals[m["ticker"]]
    assert sig["rain_in"] == 0.12 and sig["station"] == "KNYC"
    assert sig["price_at_report"]["yes_ask"] == 0.60
    bets = w.journal.rows["watch_decisions"]
    assert len(bets) == 1 and bets[0]["source"] == "watcher" and bets[0]["outcome"] == "yes"
    assert 150 <= bets[0]["count"] <= 166 and bets[0]["est_cost"] <= 100.5
    assert any("PRETEND BET" in line for line in lines) and w.urgent

    # Everything reads the bet back from disk, inside the shared account.
    j = Journal(tmp_path / "data")
    assert [r["ticker"] for r in j.paper_positions()] == [m["ticker"]]
    assert any(d.get("source") == "watcher" for d in j.rows["decisions"])

    # Market follows: price after 5 and 30 minutes is recorded once each.
    m["yes_bid_dollars"], m["yes_ask_dollars"] = "0.9500", "0.9700"
    for minutes in (62, 62, 88):
        clock.t = NOW + timedelta(minutes=minutes)
        w.next_market_check = clock.t
        w.tick()
    follow = [r for r in w.journal.rows["watch_signals"] if r["kind"] == "followup"]
    assert [(r["after_min"], r["yes_ask"]) for r in follow] == [(5, 0.97), (30, 0.97)]
    assert len(w.journal.rows["watch_decisions"]) == 1          # no second bet on the same market

    # Settled bets from the watcher are not sent to Claude for review.
    j.append("outcomes", {"env": "shadow", "ticker": m["ticker"], "result": "yes"})
    assert pending_reviews(Journal(tmp_path / "data")) == []


def test_market_already_knew_signal_but_no_bet(tmp_path):
    m = rain_market(yes_bid=0.98, yes_ask=0.99)
    w, lines = make_watcher(tmp_path, [m], [metar(NOW - timedelta(minutes=9), "0005")])
    w.tick()
    assert m["ticker"] in w.signals and not w.journal.rows["watch_decisions"]
    assert any("no bet" in line for line in lines)


def test_dry_run_and_switch_off_write_nothing(tmp_path):
    m = rain_market()
    w, lines = make_watcher(tmp_path, [m], [metar(NOW - timedelta(minutes=9), "0010")], dry_run=True)
    w.tick()
    w.tick()
    assert not (tmp_path / "data" / "watch_signals.jsonl").exists()
    assert sum("PRETEND BET" in line for line in lines) == 1

    off = tmp_path / "off"
    off.mkdir()
    w2, _ = make_watcher(off, [m], [metar(NOW - timedelta(minutes=9), "0010")])
    w2.w["enabled"] = False
    w2.tick()
    assert m["ticker"] in w2.signals and not w2.journal.rows["watch_decisions"]


def test_not_that_citys_day_yet_and_unknown_station(tmp_path):
    tomorrow = rain_market(day="26NOV21")
    tomorrow["close_time"] = "2026-11-22T05:00:00Z"
    unknown = rain_market(city="XYZ", cli="XYZ")
    w, lines = make_watcher(tmp_path, [tomorrow, unknown], [metar(NOW - timedelta(minutes=9), "0010")])
    w.tick()
    assert w.nws.calls == 0 and not w.signals
    assert any("no weather station found for CLIXYZ" in line for line in lines)


def test_station_override(tmp_path):
    m = rain_market(city="WPB", cli="DJT")
    w, _ = make_watcher(tmp_path, [m], [metar(NOW - timedelta(minutes=9), "0010")])
    w.tick()
    assert w.signals[m["ticker"]]["station"] == "KPBI"
