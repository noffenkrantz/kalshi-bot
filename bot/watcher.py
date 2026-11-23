"""Data watcher for Kalshi's daily rain markets ("Will it rain in <city> on <date>?").

These markets resolve YES if a weather station's official daily total is more than 0 inches
(a trace doesn't count), and they keep trading until midnight. So once the station itself has
reported measurable rain, the answer is all but known while the market is still open. The
watcher polls the stations' official reports (National Weather Service, free) and Kalshi's
live prices. Each time it sees that moment it records a "signal" with the price then, the
price when the rain report came out, and the price 5, 30 and 60 minutes later, so you can see
whether it is actually ahead of the market. When the price still leaves an edge, it places a
pretend bet in the bot's shared simulated account. No Claude, no tokens, no real money.

    python -m bot watch                   run forever (on an always-on server)
    python -m bot watch --once --dry-run  one pass, print only, change nothing
    python -m bot watch --inspect         print what the live data looks like

On a server, set GITHUB_TOKEN (a fine-grained token with Contents read/write on this repo).
The watcher clones the repo, writes only data/watch_*.jsonl and data/watch_status.json, and
pushes them, so the results page and the 4-hourly bot runs pick its bets up.
"""
from __future__ import annotations

import base64
import json
import os
import re
import signal
import subprocess
import time
import traceback
from collections import Counter, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .config import effective_risk, load_config
from .journal import Journal
from .kalshi import KalshiClient, KalshiError
from .nws import NWSClient, NWSError, Obs, Station, climate_day_bounds
from .runner import paper_account_from
from .strategy import decide, quotes
from .util import iso, parse_time, to_float, utcnow

DEFAULTS = {
    "enabled": True,
    "series": ["KXRAIN"],
    "tick_seconds": 30,
    "check_markets_every_seconds": 60,
    "check_station_every_seconds": 120,    # stations whose market is still worth buying
    "slow_station_every_seconds": 900,     # stations whose market is already priced near 100%
    "prob_after_rain": 0.98,               # chance of YES once the station has reported >= 0.01 in
    "prob_after_heavy_rain": 0.99,         # ... or at least heavy_rain_inches
    "heavy_rain_inches": 0.05,
    "min_edge": 0.04,
    "max_buy_price": 0.97,
    "push_every_minutes": 10,
    "pull_every_minutes": 10,
    "heartbeat_minutes": 60,
    "station_overrides": {"DJT": "KPBI"},  # CLI code -> weather station, where it isn't "K" + code
}
FOLLOWUP_MINUTES = (5, 30, 60)
_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


# ---- reading the markets --------------------------------------------------------------
def market_day(m: dict) -> date | None:
    """KXRAIN-26NOV23 -> 2026-11-23."""
    found = re.search(r"-(\d{2})([A-Z]{3})(\d{2})$", m.get("event_ticker") or "")
    if not found or found.group(2) not in _MONTHS:
        return None
    yy, mon, dd = found.groups()
    try:
        return date(2000 + int(yy), _MONTHS[mon], int(dd))
    except ValueError:
        return None


def cli_code(m: dict) -> str | None:
    """'...total precipitation at CLITTN in Trenton...' -> 'TTN' (the NWS climate-report site)."""
    found = re.search(r"\bat CLI([A-Z0-9]{3,4})\b", m.get("rules_primary") or "")
    return found.group(1) if found else None


def is_daily_rain_market(m: dict) -> bool:
    rules = (m.get("rules_primary") or "").lower()
    return (m.get("strike_type") == "greater" and to_float(m.get("floor_strike")) == 0
            and "total precipitation" in rules and "strictly greater than 0 inches" in rules
            and market_day(m) is not None and cli_code(m) is not None)


def safe_window(day: date, tz_name: str) -> tuple[datetime, datetime]:
    """Hours that belong to `day` under both the NWS climate day (local standard time) and the
    local calendar day, so rain counted here is in the official daily total either way."""
    lst_start, lst_end = climate_day_bounds(day, tz_name)
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(tz_name)
    cal_start = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)
    nxt = day + timedelta(days=1)
    cal_end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz).astimezone(timezone.utc)
    return max(lst_start, cal_start), min(lst_end, cal_end)


@dataclass
class RainReading:
    station: str
    rain_in: float                 # measurable rain the station has reported so far today
    first_rain_at: datetime | None  # time of the first report that showed it
    reports: int                   # reports that fall wholly inside the day
    checked_at: datetime


def read_rain(obs: list[Obs], start: datetime, end: datetime, station: str, now: datetime) -> RainReading:
    """A report's hourly rain (P group) covers the time since the previous hourly report, so a
    report only counts if that whole stretch is inside the day: at least 65 minutes after the
    day starts. Rain in the day's first hour is caught by later reports or not counted."""
    usable = [o for o in obs if o.raw and o.time - timedelta(minutes=65) >= start and o.time <= end]
    wet = [o for o in usable if (o.precip_in or 0) >= 0.01]
    if not wet:
        return RainReading(station, 0.0, None, len(usable), now)
    hourly_total = sum(o.precip_in for o in wet if o.time.minute >= 45)   # routine reports, ~:51
    rain = max([hourly_total] + [o.precip_in for o in wet])
    return RainReading(station, round(rain, 2), min(o.time for o in wet), len(usable), now)


# ---- the watcher ------------------------------------------------------------------------
class RainWatcher:
    def __init__(self, cfg: dict, kalshi: KalshiClient, nws: NWSClient, root: Path,
                 dry_run: bool = False, say=print, clock=utcnow):
        self.kalshi, self.nws, self.root = kalshi, nws, Path(root)
        self.dry_run, self.say, self.clock = dry_run, say, clock
        self.prices: dict[str, deque] = {}          # ticker -> (time, yes_bid, yes_ask), last 3 hours
        self.markets: dict[str, dict] = {}
        self.stations: dict[str, Station | None] = {}
        self.station_next: dict[str, datetime] = {}
        self.readings: dict[tuple[str, date], RainReading] = {}
        self.skip_notes: dict[str, str] = {}
        self.bet_done: set[str] = set()             # tickers bet on in this process (matters in dry runs)
        self.next_market_check = datetime.min.replace(tzinfo=timezone.utc)
        self.counts = Counter()
        self.errors: deque = deque(maxlen=5)
        self.dirty = self.urgent = False
        self.reload(cfg)

    def reload(self, cfg: dict) -> None:
        """(Re)read settings and the journal, e.g. after pulling the latest results from GitHub."""
        self.cfg = cfg
        self.w = {**DEFAULTS, **cfg.get("watcher", {})}
        self.journal = Journal(self.root / "data")
        self.signals = {r["ticker"]: r for r in self.journal.rows["watch_signals"] if r.get("kind") == "signal"}
        self.followups = {(r["ticker"], r.get("after_min")) for r in self.journal.rows["watch_signals"]
                          if r.get("kind") == "followup"}

    def log(self, msg: str) -> None:
        self.say(f"{self.clock():%Y-%m-%d %H:%M:%S}Z {msg}")

    # -- one pass ------------------------------------------------------------------------
    def tick(self) -> None:
        now = self.clock()
        if now >= self.next_market_check:
            self.refresh_markets(now)
            self.next_market_check = now + timedelta(seconds=self.w["check_markets_every_seconds"])
        for m in list(self.markets.values()):
            try:
                self.check_market(m, now)
            except NWSError as e:
                self.note_error(f"weather data for {m['ticker']}: {e}")
        self.record_followups(now)

    def refresh_markets(self, now: datetime) -> None:
        found = {}
        for series in self.w["series"]:
            for m in self.kalshi.iter_markets(max_markets=1000, series_ticker=series, status="open"):
                if is_daily_rain_market(m):
                    found[m["ticker"]] = m
        self.markets = found
        cutoff = now - timedelta(hours=3)
        for ticker, m in found.items():
            q = quotes(m)
            hist = self.prices.setdefault(ticker, deque())
            hist.append((now, q.yes_bid, q.yes_ask))
            while hist and hist[0][0] < cutoff:
                hist.popleft()

    def station_for(self, m: dict) -> Station | None:
        code = cli_code(m)
        if code in self.stations:
            return self.stations[code]
        override = self.w["station_overrides"].get(code)
        for sid in [s for s in (override, f"K{code}") if s]:
            try:
                st = self.nws.station(sid)
                self.stations[code] = st
                return st
            except NWSError:
                continue
        self.log(f"no weather station found for CLI{code} ({m['ticker']}); skipping it")
        self.stations[code] = None
        return None

    def check_market(self, m: dict, now: datetime) -> None:
        st = self.station_for(m)
        day = market_day(m)
        if st is None or day is None:
            return
        start, end = safe_window(day, st.tz)
        close = parse_time(m.get("close_time"))
        if not (start <= now <= end) or (close and close <= now):
            return                                   # not that city's day yet (or it's over)
        ticker = m["ticker"]
        key = (st.id, day)
        q = quotes(m)
        holding = ticker in self.journal_held()
        worth_buying = q.yes_ask is not None and q.yes_ask <= self.w["max_buy_price"] and not holding
        reading = self.readings.get(key)
        if not (reading and reading.rain_in >= 0.01) and now >= self.station_next.get(st.id, now):
            obs = self.nws.observations(st.id, start)
            reading = read_rain(obs, start, end, st.id, now)
            self.readings[key] = reading
            self.counts["station_checks"] += 1
            wait = self.w["check_station_every_seconds"] if worth_buying else self.w["slow_station_every_seconds"]
            self.station_next[st.id] = now + timedelta(seconds=wait)
        if reading and reading.rain_in >= 0.01:
            self.on_rain(m, st, reading, now)

    def journal_held(self) -> set:
        return {r["ticker"] for r in self.journal.paper_positions()}

    # -- rain seen ----------------------------------------------------------------------
    def price_at(self, ticker: str, t: datetime | None):
        if t is None:
            return None
        hist = self.prices.get(ticker) or ()
        before = [h for h in hist if h[0] <= t]
        if not before:
            return None
        ts, bid, ask = before[-1]
        return {"at": iso(ts), "yes_bid": bid, "yes_ask": ask}

    def on_rain(self, m: dict, st: Station, reading: RainReading, now: datetime) -> None:
        ticker, q = m["ticker"], quotes(m)
        if ticker not in self.signals:
            row = {"kind": "signal", "ticker": ticker, "event_ticker": m.get("event_ticker"),
                   "question": m.get("title"), "station": st.id, "station_name": st.name,
                   "rain_in": reading.rain_in, "first_rain_report": iso(reading.first_rain_at),
                   "detected": iso(now), "yes_bid": q.yes_bid, "yes_ask": q.yes_ask,
                   "ask_size": q.yes_ask_size, "price_at_report": self.price_at(ticker, reading.first_rain_at),
                   "close_time": m.get("close_time")}
            self.signals[ticker] = row
            self.counts["signals"] += 1
            ago = (now - reading.first_rain_at).total_seconds() / 60
            self.log(f"RAIN at {st.id} ({st.name}): {reading.rain_in:.2f} in, first reported "
                     f"{ago:.0f} min ago. {ticker} YES now {q.yes_bid}/{q.yes_ask}")
            if not self.dry_run:
                self.journal.append("watch_signals", {"ts": iso(now), **row})
                self.dirty = self.urgent = True
        self.maybe_bet(m, st, reading, now)

    def trading_blocked(self) -> str | None:
        if not self.w.get("enabled", True):
            return "watcher is switched off in config.toml ([watcher] enabled = false)"
        if (self.root / "STOP").exists():
            return "a STOP file exists in the repo"
        if self.journal.state.get("halted:shadow"):
            return "the simulated account is halted"
        return None

    def maybe_bet(self, m: dict, st: Station, reading: RainReading, now: datetime) -> None:
        ticker = m["ticker"]
        if ticker in self.bet_done or ticker in self.journal_held():
            return
        blocked = self.trading_blocked()
        if blocked:
            self.note_skip(ticker, blocked)
            return
        heavy = reading.rain_in >= self.w["heavy_rain_inches"]
        p = self.w["prob_after_heavy_rain"] if heavy else self.w["prob_after_rain"]
        est = {"prob_yes": p, "confidence": "high", "rules_clear": True}
        strat = {**self.cfg["strategy"], "min_edge": self.w["min_edge"], "min_buy_price": 0.01,
                 "max_buy_price": self.w["max_buy_price"], "one_position_per_event": False}
        acct = paper_account_from(self.journal, self.cfg, now.strftime("%Y-%m-%d"))
        d = decide(m, est, strat, effective_risk(self.cfg, "shadow"), acct)
        if d.action != "buy_yes":
            self.note_skip(ticker, d.reason)
            return
        q = quotes(m)
        reason = (f"{st.id} ({st.name}) reported {reading.rain_in:.2f} in of rain "
                  f"(first at {reading.first_rain_at:%H:%M}Z); YES was {d.outcome_price:.2f}")
        row = {"ts": iso(now), "env": "shadow", "source": "watcher", "ticker": ticker,
               "event_ticker": m.get("event_ticker"), "category": "Climate and Weather",
               "question": m.get("title"), "close_time": m.get("close_time"), "market_mid": q.mid,
               "prob_yes": p, "edge": d.edge, "action": "paper_buy_yes", "reason": reason,
               "outcome": "yes", "outcome_price": d.outcome_price, "count": d.count, "est_cost": d.est_cost,
               "station": st.id, "rain_in": reading.rain_in}
        self.counts["bets"] += 1
        self.bet_done.add(ticker)
        self.log(f"PRETEND BET: {d.count} YES on {ticker} at ${d.outcome_price:.2f} "
                 f"(edge {d.edge:+.2f}/contract, ~${d.est_cost:.2f}). {reason}")
        if not self.dry_run:
            self.journal.append("watch_decisions", row)
            self.dirty = self.urgent = True

    def note_skip(self, ticker: str, reason: str) -> None:
        if self.skip_notes.get(ticker) != reason:
            self.skip_notes[ticker] = reason
            self.log(f"no bet on {ticker}: {reason}")

    def note_error(self, msg: str) -> None:
        self.errors.append(f"{iso(self.clock())} {msg}")
        self.log(f"error: {msg}")

    # -- did the market follow? -------------------------------------------------------
    def record_followups(self, now: datetime) -> None:
        for ticker, s in self.signals.items():
            detected = parse_time(s.get("detected"))
            if not detected or now - detected > timedelta(minutes=max(FOLLOWUP_MINUTES) + 30):
                continue
            for after in FOLLOWUP_MINUTES:
                if (ticker, after) in self.followups or now < detected + timedelta(minutes=after):
                    continue
                m = self.markets.get(ticker)
                q = quotes(m) if m else None
                row = {"kind": "followup", "ticker": ticker, "signal_detected": s.get("detected"),
                       "after_min": after, "yes_bid": q.yes_bid if q else None,
                       "yes_ask": q.yes_ask if q else None, "market_open": m is not None}
                self.followups.add((ticker, after))
                self.log(f"{ticker} {after} min after the signal: YES {row['yes_bid']}/{row['yes_ask']}")
                if not self.dry_run:
                    self.journal.append("watch_signals", {"ts": iso(now), **row})
                    self.dirty = True

    def status(self, now: datetime) -> dict:
        today = now.strftime("%Y-%m-%d")
        live = [m for m in self.markets.values() if (st := self.stations.get(cli_code(m)))
                and market_day(m) and safe_window(market_day(m), st.tz)[0] <= now]
        return {"updated": iso(now), "markets_open": len(self.markets), "markets_in_play": len(live),
                "stations_known": sum(1 for s in self.stations.values() if s),
                "signals_today": sum(1 for s in self.signals.values() if (s.get("detected") or "").startswith(today)),
                "bets_today": sum(1 for r in self.journal.rows["watch_decisions"] if r.get("ts", "").startswith(today)),
                "station_checks_since_start": self.counts["station_checks"], "recent_errors": list(self.errors)}


# ---- keeping the repo in sync (server only) ---------------------------------------------
class RepoSync:
    """A clone of the repo that the watcher reads settings and results from, and pushes its own
    watch_* files to. The token goes in an HTTP header in the clone's git config, never in a URL,
    so it can't show up in logs."""

    FILES = ("data/watch_decisions.jsonl", "data/watch_signals.jsonl", "data/watch_status.json")

    def __init__(self, repo_dir: Path, slug: str, token: str, say=print):
        self.dir, self.slug, self.say = Path(repo_dir), slug, say
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        self.header = f"AUTHORIZATION: basic {basic}"

    def git(self, *args: str, timeout: int = 120) -> tuple[int, str]:
        try:
            r = subprocess.run(["git", "-C", str(self.dir), *args], capture_output=True, text=True, timeout=timeout)
            return r.returncode, (r.stdout + r.stderr).strip()
        except subprocess.TimeoutExpired:
            return 1, f"git {args[0]} timed out"

    def ensure_clone(self) -> None:
        if (self.dir / ".git").exists():
            return
        self.dir.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["git", "-c", f"http.https://github.com/.extraheader={self.header}", "clone", "-q",
                            f"https://github.com/{self.slug}.git", str(self.dir)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"could not clone {self.slug}: {(r.stderr or r.stdout).strip()[:300]}")
        self.git("config", "--local", "http.https://github.com/.extraheader", self.header)
        self.git("config", "--local", "user.name", "kalshi-watcher")
        self.git("config", "--local", "user.email", "kalshi-watcher@users.noreply.github.com")
        self.say(f"cloned {self.slug}")

    def pull(self) -> bool:
        code, out = self.git("pull", "-q", "--rebase", "--autostash")
        if code:
            self.say(f"git pull failed: {out[:300]}")
        return code == 0

    def push(self, message: str) -> bool:
        present = [f for f in self.FILES if (self.dir / f).exists()]
        if not present:
            return True
        self.git("add", "--", *present)
        if self.git("diff", "--cached", "--quiet")[0] == 0:
            return True
        code, out = self.git("commit", "-q", "-m", message)
        if code:
            self.say(f"git commit failed: {out[:300]}")
            return False
        for attempt in range(3):
            self.pull()
            code, out = self.git("push", "-q")
            if code == 0:
                return True
            time.sleep(5 * (attempt + 1))
        self.say(f"git push failed (will retry): {out[:300]}")
        return False


# ---- running it -------------------------------------------------------------------------
def serve(once: bool = False, dry_run: bool = False, root: Path | None = None, say=print) -> int:
    token = os.environ.get("GITHUB_TOKEN")
    slug = os.environ.get("WATCH_REPO", "noffenkrantz/kalshi-bot")
    sync = None
    if token and not dry_run:
        repo_dir = Path(os.environ.get("WATCH_DIR", "/tmp/kalshi-bot-repo"))
        sync = RepoSync(repo_dir, slug, token, say)
        sync.ensure_clone()
        sync.pull()
        root = repo_dir
    else:
        from .config import ROOT
        root = root or ROOT
        if not dry_run:
            say("No GITHUB_TOKEN: results stay in this folder and are not pushed anywhere.")
    cfg = load_config(root / "config.toml")
    watcher = RainWatcher(cfg, KalshiClient("prod"), NWSClient(), root, dry_run=dry_run, say=say)
    w = watcher.w
    watcher.log(f"watcher started ({'dry run, ' if dry_run else ''}series {', '.join(w['series'])})")

    stopping = {"now": False}

    def _stop(*_):
        stopping["now"] = True
    signal.signal(signal.SIGTERM, _stop)

    last_push = last_pull = last_beat = time.monotonic()
    while True:
        started = time.monotonic()
        try:
            watcher.tick()
        except KalshiError as e:
            watcher.note_error(f"Kalshi: {e}")
        except Exception as e:   # keep running; the next pass will try again
            watcher.note_error(f"{type(e).__name__}: {e}")
            traceback.print_exc()
        now_m = time.monotonic()
        if sync:
            beat = now_m - last_beat >= w["heartbeat_minutes"] * 60
            if watcher.urgent or stopping["now"] or beat or (
                    watcher.dirty and now_m - last_push >= w["push_every_minutes"] * 60):
                status = watcher.status(watcher.clock())
                (root / "data" / "watch_status.json").write_text(json.dumps(status, indent=1) + "\n")
                what = f"{status['signals_today']} rain signals, {status['bets_today']} pretend bets today"
                if sync.push(f"watcher: {what}"):
                    watcher.dirty = watcher.urgent = False
                    last_push = last_beat = now_m
            if now_m - last_pull >= w["pull_every_minutes"] * 60 and not stopping["now"]:
                if sync.pull():
                    watcher.reload(load_config(root / "config.toml"))
                last_pull = now_m
        if once or stopping["now"]:
            if once:
                s = watcher.status(watcher.clock())
                watcher.log(f"one pass done: {s['markets_open']} open rain markets, {s['markets_in_play']} in play "
                            f"today, {s['stations_known']} stations found, {s['station_checks_since_start']} station "
                            f"checks, {s['signals_today']} signals today")
            return 0
        while time.monotonic() - started < w["tick_seconds"] and not stopping["now"]:
            time.sleep(1)   # short naps, so a shutdown request is handled within a second


# ---- inspect ------------------------------------------------------------------------------
def inspect(kalshi: KalshiClient, nws: NWSClient, say=print) -> None:
    now = utcnow()
    say(f"# Watcher inspect, {now:%Y-%m-%d %H:%M} UTC\n")
    markets = [m for m in kalshi.iter_markets(max_markets=1000, series_ticker="KXRAIN", status="open")]
    daily = [m for m in markets if is_daily_rain_market(m)]
    say(f"KXRAIN open markets: {len(markets)}, recognised as daily rain markets: {len(daily)}")
    for m in markets:
        if m not in daily:
            say(f"  NOT recognised: {m.get('ticker')} | {m.get('rules_primary')}")
    by_code = Counter(cli_code(m) for m in daily)
    say(f"Climate-report sites: {', '.join(sorted(c for c in by_code if c))}")
    for code in sorted(c for c in by_code if c):
        override = DEFAULTS["station_overrides"].get(code)
        for sid in [s for s in (override, f"K{code}") if s]:
            try:
                st = nws.station(sid)
                say(f"  CLI{code} -> {st.id} {st.name} ({st.tz})")
                break
            except NWSError as e:
                say(f"  CLI{code} -> {sid}: {str(e)[:120]}")
    for m in daily[:3]:
        say(f"  {m['ticker']}: day {market_day(m)}, closes {m.get('close_time')}, "
            f"YES {m.get('yes_bid_dollars')}/{m.get('yes_ask_dollars')}")
