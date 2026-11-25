"""The bot's always-on home (Render): one process that runs everything on its own clock.

    python -m bot watch [--once] [--dry-run]   the rain watcher + the gap tracker (what render.yaml runs)
    python -m bot serve                    also a research run every 4 hours (not used by default:
                                           research runs on GitHub when you press Run)

Every 4 hours it does what a GitHub run used to do, in a clone of the repo: simulated trading
with Claude's research, the lag scan, and the report (README, REPORT.md, LAGS.md, the results
page), then commits and pushes. Pushing site/ triggers the GitHub Pages publish. Between runs
it ticks the rain watcher every 30 seconds.

Research runs use the clone's code (python -m bot ... inside the clone), so changes pushed to
the repo take effect at the next run without redeploying. GitHub Actions stays as a backup:
its workflow only runs if no run has happened for 5 hours.

The gap tracker (bot/gaps.py, Pinnacle vs Kalshi sports prices) runs every [gaps] every_minutes
when PINNAPI_KEY is set, also in the clone, and pushes only its own gap files.

Needs GITHUB_TOKEN (fine-grained, Contents read/write on this repo); ANTHROPIC_API_KEY for
research; PINNAPI_KEY for the gap tracker.
"""
from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from .config import ROOT, load_config
from .gaps import last_snapshot, settings as gap_settings
from .kalshi import KalshiClient, KalshiError
from .nws import NWSClient
from .util import iso, parse_time, utcnow
from .watcher import RainWatcher

RUN_EVERY = timedelta(hours=4)
RESULT_PATHS = ("data", "README.md", "REPORT.md", "LAGS.md", "site")
GAP_PATHS = ("data/gap_snaps.jsonl", "data/gap_bets.jsonl", "data/gap_outcomes.jsonl", "data/gap_state.json", "GAPS.md")
STEP_TIMEOUT = 40 * 60


# ---- the repo clone ------------------------------------------------------------------------
class RepoSync:
    """A clone of the repo that the server reads settings and results from and pushes results to.
    The token goes in an HTTP header in the clone's git config, never in a URL, so it can't show
    up in logs."""

    WATCH_FILES = ("data/watch_decisions.jsonl", "data/watch_signals.jsonl", "data/watch_status.json")

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
        self.git("config", "--local", "user.name", "kalshi-bot")
        self.git("config", "--local", "user.email", "kalshi-bot@users.noreply.github.com")
        self.say(f"cloned {self.slug}")

    def pull(self) -> bool:
        code, out = self.git("pull", "-q", "--rebase", "--autostash")
        if code:
            self.say(f"git pull failed: {out[:300]}")
        return code == 0

    def push(self, message: str, paths=WATCH_FILES) -> bool:
        present = [p for p in paths if (self.dir / p).exists()]
        if not present:
            return True
        self.git("add", "-A", "--", *present)
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


def last_run_time(root: Path) -> datetime | None:
    """From the first line of data/last_run.log: '# Last run: 2026-11-23 13:37 UTC'."""
    try:
        first = (root / "data" / "last_run.log").read_text().splitlines()[0]
    except (OSError, IndexError):
        return None
    if not first.startswith("# Last run: "):
        return None
    return parse_time(first[len("# Last run: "):].replace(" UTC", "").replace(" ", "T") + ":00+00:00")


# ---- the supervisor ------------------------------------------------------------------------
class Supervisor:
    def __init__(self, root: Path, sync: RepoSync | None, research: bool = True, dry_run: bool = False,
                 say=print, clock=utcnow, runner=subprocess.run, watcher: RainWatcher | None = None):
        self.root, self.sync, self.research, self.dry_run = Path(root), sync, research, dry_run
        self.say, self.clock, self.runner = say, clock, runner
        self.cfg = load_config(self.root / "config.toml")
        self.watcher = watcher or RainWatcher(self.cfg, KalshiClient("prod"), NWSClient(), self.root,
                                              dry_run=dry_run, say=say)
        now = clock()
        self.last_push = self.last_pull = self.last_beat = now
        self.last_research_error: str | None = None
        self.last_gaps_error: str | None = None
        self.last_gaps_attempt: datetime | None = None
        self.stopping = False

    def log(self, msg: str) -> None:
        self.say(f"{self.clock():%Y-%m-%d %H:%M:%S}Z {msg}")

    # -- research every 4 hours ---------------------------------------------------------
    def research_due(self, now: datetime) -> bool:
        last = last_run_time(self.root)
        return last is None or now - last >= RUN_EVERY - timedelta(minutes=1)

    def research_cycle(self, now: datetime) -> bool:
        """What a GitHub run did: trade (simulated), lag scan, report; then commit and push."""
        if self.sync:
            self.sync.pull()
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        log = self.root / "data" / "last_run.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"# Last run: {now:%Y-%m-%d %H:%M} UTC\nbrain: {'API key' if has_key else 'NOT SET UP'} (Render)\n")
        steps = [("run --mode shadow", ["run", "--mode", "shadow"]), ("lag scan", ["lags", "--scan"]),
                 ("report", ["report"])]
        if not has_key:
            steps = steps[1:]
            with open(log, "a") as f:
                f.write("Add ANTHROPIC_API_KEY to the Render service's environment to turn on research and trading.\n")
        env = {**os.environ, "GITHUB_REPOSITORY": self.sync.slug if self.sync else os.environ.get("GITHUB_REPOSITORY", ""),
               "GITHUB_SERVER_URL": "https://github.com", "PYTHONUNBUFFERED": "1"}
        env.pop("GITHUB_TOKEN", None)     # the research steps never need it
        self.log(f"research run starting ({'with' if has_key else 'WITHOUT'} Claude)")
        ok = True
        for title, args in steps:
            try:
                r = self.runner([sys.executable, "-m", "bot", *args], cwd=str(self.root), env=env,
                                capture_output=True, text=True, timeout=STEP_TIMEOUT)
                out, code = (r.stdout or "") + (r.stderr or ""), r.returncode
            except subprocess.TimeoutExpired:
                out, code = f"{title} timed out after {STEP_TIMEOUT // 60} minutes\n", 1
            with open(log, "a") as f:
                f.write(f"\n## {title}\n{out}")
            for line in out.strip().splitlines()[-4:]:
                self.log(f"  {title}: {line[:200]}")
            if code:
                ok = False
                self.last_research_error = f"{title} exited with {code}"
        if self.sync and not self.dry_run:
            if not self.sync.push(f"journal: run {now:%Y-%m-%dT%H:%MZ}", RESULT_PATHS):
                ok = False
        self.cfg = load_config(self.root / "config.toml")
        self.watcher.reload(self.cfg)
        self.log(f"research run {'done' if ok else 'finished with problems'}")
        return ok

    # -- gap tracker (Pinnacle vs Kalshi), on its own clock ------------------------------
    def gaps_on(self) -> bool:
        return bool(os.environ.get("PINNAPI_KEY")) and bool(gap_settings(self.cfg)["enabled"])

    def gaps_due(self, now: datetime) -> bool:
        last = last_snapshot(self.root)
        every = timedelta(minutes=float(gap_settings(self.cfg)["every_minutes"]))
        tried = self.last_gaps_attempt      # also in memory, so a snapshot that fails early isn't retried every tick
        return (self.gaps_on() and (last is None or now - last >= every - timedelta(minutes=1))
                and (tried is None or now - tried >= every - timedelta(minutes=1)))

    def gaps_cycle(self, now: datetime) -> bool:
        self.last_gaps_attempt = now
        if self.sync:
            self.sync.pull()
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        env.pop("GITHUB_TOKEN", None)
        try:
            r = self.runner([sys.executable, "-m", "bot", "gaps"], cwd=str(self.root), env=env,
                            capture_output=True, text=True, timeout=15 * 60)
            out, code = (r.stdout or "") + (r.stderr or ""), r.returncode
        except subprocess.TimeoutExpired:
            out, code = "gap snapshot timed out after 15 minutes\n", 1
        for line in out.strip().splitlines()[-8:]:
            self.log(f"  gaps: {line[:200]}")
        self.last_gaps_error = f"gap snapshot exited with {code}" if code else None
        if self.sync and not self.dry_run:
            self.sync.push(f"gaps: snapshot {now:%Y-%m-%dT%H:%MZ}", GAP_PATHS)
        return code == 0

    # -- one loop pass -------------------------------------------------------------------------
    def step(self) -> None:
        now = self.clock()
        if self.research and self.research_due(now):
            try:
                self.research_cycle(now)
            except Exception as e:      # never let a bad run stop the server
                self.last_research_error = f"{type(e).__name__}: {e}"
                self.log(f"research run failed: {e}")
                traceback.print_exc()
        if self.gaps_due(now):
            try:
                self.gaps_cycle(now)
            except Exception as e:      # never let the gap tracker stop the server
                self.last_gaps_error = f"{type(e).__name__}: {e}"
                self.log(f"gap snapshot failed: {e}")
                traceback.print_exc()
        try:
            self.watcher.tick()
        except KalshiError as e:
            self.watcher.note_error(f"Kalshi: {e}")
        except Exception as e:
            self.watcher.note_error(f"{type(e).__name__}: {e}")
            traceback.print_exc()
        self.save_watcher(self.clock())

    def status(self, now: datetime) -> dict:
        s = self.watcher.status(now)
        last = last_run_time(self.root)
        s.update(host="render" if os.environ.get("RENDER") else "server", research=self.research,
                 last_research_run=iso(last) if last else None,
                 next_research_run=iso(last + RUN_EVERY) if last else None,
                 last_research_error=self.last_research_error, gap_tracker=self.gaps_on(),
                 last_gap_snapshot=iso(last_snapshot(self.root)) if last_snapshot(self.root) else None,
                 last_gaps_error=self.last_gaps_error)
        return s

    def save_watcher(self, now: datetime) -> None:
        if not self.sync or self.dry_run:
            return
        w = self.watcher.w
        beat = now - self.last_beat >= timedelta(minutes=w["heartbeat_minutes"])
        if self.watcher.urgent or self.stopping or beat or (
                self.watcher.dirty and now - self.last_push >= timedelta(minutes=w["push_every_minutes"])):
            status = self.status(now)
            (self.root / "data" / "watch_status.json").write_text(json.dumps(status, indent=1) + "\n")
            what = f"{status['signals_today']} rain signals, {status['bets_today']} pretend bets today"
            if self.sync.push(f"watcher: {what}"):
                self.watcher.dirty = self.watcher.urgent = False
                self.last_push = self.last_beat = now
        if now - self.last_pull >= timedelta(minutes=w["pull_every_minutes"]) and not self.stopping:
            if self.sync.pull():
                self.cfg = load_config(self.root / "config.toml")
                self.watcher.reload(self.cfg)
            self.last_pull = now


def main(research: bool = True, once: bool = False, dry_run: bool = False, say=print) -> int:
    token = os.environ.get("GITHUB_TOKEN")
    slug = os.environ.get("WATCH_REPO", "noffenkrantz/kalshi-bot")
    sync, root = None, ROOT
    if token and not dry_run:
        sync = RepoSync(Path(os.environ.get("WATCH_DIR", "/tmp/kalshi-bot-repo")), slug, token, say)
        sync.ensure_clone()
        sync.pull()
        root = sync.dir
    elif research and not dry_run:
        say("GITHUB_TOKEN is not set: add it to the service's environment (see SETUP.md). Nothing will be saved.")
    sup = Supervisor(root, sync, research=research and not dry_run, dry_run=dry_run, say=say)
    last = last_run_time(root)
    sup.log(f"server started: {'research every 4 hours + ' if sup.research else ''}rain watcher"
            f"{' + gap tracker every ' + str(gap_settings(sup.cfg)['every_minutes']) + ' min' if sup.gaps_on() else ' (gap tracker off: no PINNAPI_KEY)'}"
            f"{' (dry run)' if dry_run else ''}; last research run {iso(last) if last else 'never'}")

    def _stop(*_):
        sup.stopping = True
    signal.signal(signal.SIGTERM, _stop)

    while True:
        started = time.monotonic()
        sup.step()
        if once or sup.stopping:
            if once:
                s = sup.status(sup.clock())
                sup.log(f"one pass done: {s['markets_open']} open rain markets, {s['markets_in_play']} in play today, "
                        f"{s['stations_known']} stations found, {s['signals_today']} signals today")
            return 0
        while time.monotonic() - started < sup.watcher.w["tick_seconds"] and not sup.stopping:
            time.sleep(1)   # short naps, so a shutdown request is handled within a second
