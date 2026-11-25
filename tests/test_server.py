"""Offline tests for the always-on server: fake git, fake commands, fake clock."""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.server import GAP_PATHS, RESULT_PATHS, RepoSync, Supervisor, last_run_time
from bot.watcher import DEFAULTS

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 24, 1, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class FakeSync:
    slug = "someone/kalshi-bot"

    def __init__(self):
        self.pulls, self.pushes = 0, []

    def pull(self):
        self.pulls += 1
        return True

    def push(self, message, paths=("data/watch_status.json",)):
        self.pushes.append((message, tuple(paths)))
        return True


class FakeWatcher:
    def __init__(self):
        self.w = dict(DEFAULTS)
        self.ticks, self.reloads, self.dirty, self.urgent, self.errors = 0, 0, False, False, []

    def tick(self):
        self.ticks += 1

    def reload(self, cfg):
        self.reloads += 1

    def note_error(self, msg):
        self.errors.append(msg)

    def status(self, now):
        return {"markets_open": 3, "markets_in_play": 1, "stations_known": 1, "signals_today": 0, "bets_today": 0}


class FakeRunner:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, cmd, cwd, env, capture_output, text, timeout):
        self.calls.append((cmd[3:], cwd, env))
        code = 1 if self.fail and self.fail in cmd else 0
        return subprocess.CompletedProcess(cmd, code, stdout=f"did {' '.join(cmd[3:])}\n", stderr="")


def make(tmp_path, last_run=None, clock=None, runner=None):
    shutil.copy(ROOT / "config.toml", tmp_path / "config.toml")
    (tmp_path / "data").mkdir()
    if last_run:
        (tmp_path / "data" / "last_run.log").write_text(f"# Last run: {last_run:%Y-%m-%d %H:%M} UTC\nbrain: API key\n")
    lines = []
    sup = Supervisor(tmp_path, FakeSync(), say=lines.append, clock=clock or Clock(NOW),
                     runner=runner or FakeRunner(), watcher=FakeWatcher())
    return sup, lines


def test_last_run_time(tmp_path):
    (tmp_path / "data").mkdir()
    assert last_run_time(tmp_path) is None
    (tmp_path / "data" / "last_run.log").write_text("# Last run: 2026-11-23 13:37 UTC\nbrain: API key\n")
    assert last_run_time(tmp_path) == datetime(2026, 11, 23, 13, 37, tzinfo=timezone.utc)


def test_research_runs_every_four_hours(tmp_path):
    sup, _ = make(tmp_path, last_run=NOW - timedelta(hours=3, minutes=50))
    assert not sup.research_due(NOW)
    assert sup.research_due(NOW + timedelta(minutes=10))
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    assert make(fresh)[0].research_due(NOW)                  # never run: run now


def test_research_cycle_runs_the_steps_logs_and_pushes(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-secret")
    runner = FakeRunner()
    sup, lines = make(tmp_path, last_run=NOW - timedelta(hours=5), runner=runner)
    sup.step()
    assert [c[0] for c in runner.calls] == [["run", "--mode", "shadow"], ["lags", "--scan"], ["report"]]
    assert all(c[1] == str(tmp_path) for c in runner.calls)
    env = runner.calls[0][2]
    assert "GITHUB_TOKEN" not in env and env["GITHUB_REPOSITORY"] == "someone/kalshi-bot"
    log = (tmp_path / "data" / "last_run.log").read_text()
    assert log.startswith(f"# Last run: {NOW:%Y-%m-%d %H:%M} UTC") and "## lag scan\ndid lags --scan" in log
    assert sup.sync.pushes[0] == (f"journal: run {NOW:%Y-%m-%dT%H:%MZ}", RESULT_PATHS)
    assert sup.watcher.ticks == 1 and sup.watcher.reloads == 1
    assert last_run_time(tmp_path) == NOW.replace(second=0) and not sup.research_due(NOW + timedelta(hours=1))


def test_without_api_key_it_still_scans_and_reports(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runner = FakeRunner()
    sup, _ = make(tmp_path, runner=runner)
    sup.research_cycle(NOW)
    assert [c[0] for c in runner.calls] == [["lags", "--scan"], ["report"]]
    assert "NOT SET UP" in (tmp_path / "data" / "last_run.log").read_text()


def test_a_failing_step_is_reported_but_the_rest_still_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    runner = FakeRunner(fail="lags")
    sup, lines = make(tmp_path, runner=runner)
    assert sup.research_cycle(NOW) is False
    assert [c[0] for c in runner.calls][-1] == ["report"] and sup.sync.pushes
    assert sup.last_research_error == "lag scan exited with 1"


def test_watcher_heartbeat_and_status(tmp_path):
    clock = Clock(NOW)
    sup, _ = make(tmp_path, last_run=NOW - timedelta(hours=1), clock=clock)
    sup.step()
    assert sup.sync.pushes == []                              # nothing to save yet
    clock.t = NOW + timedelta(minutes=61)
    sup.step()
    assert sup.sync.pushes and sup.sync.pushes[-1][0].startswith("watcher:")
    status = (tmp_path / "data" / "watch_status.json").read_text()
    assert '"next_research_run": "2026-11-24T04:00:00+00:00"' in status


def test_gap_tracker_runs_hourly_only_with_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("PINNAPI_KEY", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-secret")
    clock, runner = Clock(NOW), FakeRunner()
    sup, _ = make(tmp_path, last_run=NOW - timedelta(hours=1), clock=clock, runner=runner)
    cfgfile = tmp_path / "config.toml"                       # stays hourly when the server re-reads its settings
    cfgfile.write_text(cfgfile.read_text().replace('mode = "live"', 'mode = "hourly"'))
    sup.cfg["gaps"]["mode"] = "hourly"
    sup.step()
    assert runner.calls == [] and not sup.status(NOW)["gap_tracker"]          # no key: off
    monkeypatch.setenv("PINNAPI_KEY", "pk-test")
    sup.step()
    assert [c[0] for c in runner.calls] == [["gaps"]]
    env = runner.calls[0][2]
    assert env["PINNAPI_KEY"] == "pk-test" and "GITHUB_TOKEN" not in env
    assert sup.sync.pushes[-1] == (f"gaps: snapshot {NOW:%Y-%m-%dT%H:%MZ}", GAP_PATHS)
    clock.t = NOW + timedelta(minutes=30)
    sup.step()
    assert len(runner.calls) == 1                                           # not again for an hour,
    (tmp_path / "data" / "gap_state.json").write_text('{"day": "2026-11-24", "calls": 4, "last_run": "%s"}'
                                                      % (NOW + timedelta(minutes=50)).isoformat())
    clock.t = NOW + timedelta(minutes=61)
    sup.step()
    assert len(runner.calls) == 1                                           # counting from the last snapshot
    clock.t = NOW + timedelta(minutes=111)
    sup.step()
    assert len(runner.calls) == 2 and sup.status(clock.t)["last_gap_snapshot"].startswith("2026-11-24T01:50")


class FakeLive:
    def __init__(self):
        self.ticks, self.dirty, self.new_bets = 0, False, 0

    def tick(self):
        self.ticks += 1
        self.dirty, self.new_bets = True, 1

    def reload(self, cfg):
        pass


def test_live_gap_mode_ticks_fast_and_pushes_new_bets_at_once(tmp_path, monkeypatch):
    monkeypatch.setenv("PINNAPI_KEY", "pk-test")
    runner = FakeRunner()
    sup, _ = make(tmp_path, last_run=NOW - timedelta(hours=1), runner=runner)
    sup.cfg["gaps"]["mode"] = "hourly"
    sup.sync_live_mode()
    assert sup.live is None
    sup.cfg["gaps"]["mode"] = "live"
    sup.sync_live_mode()
    assert sup.live is not None and not sup.gaps_due(NOW)    # no hourly snapshots in live mode
    sup.live = FakeLive()
    sup.fast_tick()
    assert sup.live.ticks == 1 and sup.sync.pushes[-1][1] == GAP_PATHS and "1 new bets" in sup.sync.pushes[-1][0]
    assert not sup.live.dirty and runner.calls == []
    sup.cfg["gaps"]["mode"] = "hourly"
    sup.sync_live_mode()
    assert sup.live is None


def test_a_push_permission_error_backs_off_instead_of_retrying_every_tick(tmp_path):
    lines, t = [], [1000.0]
    sync = RepoSync(tmp_path, "someone/kalshi-bot", "ghp-x", say=lines.append, sleep=lambda s: None, clock=lambda: t[0])
    calls = []

    def fake_git(*args, timeout=120):
        calls.append(args[0])
        if args[0] == "push":
            return (0, "") if t[0] > 2000 else (128, "remote: Permission to someone/kalshi-bot.git denied to someone.\n"
                                                      "fatal: ... The requested URL returned error: 403")
        return 0, ""
    sync.git = fake_git
    assert sync.push_commits() is False and calls.count("push") == 1            # no 3x retry for a 403
    assert any("DENIED" in x for x in lines)
    t[0] = 1300.0
    assert sync.push_commits() is False and calls.count("push") == 1            # still backing off
    t[0] = 2100.0
    assert sync.push_commits() is True and any("works again" in x for x in lines)
