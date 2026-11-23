"""The bot's notebook: append-only JSON Lines files in data/.

Plain text on purpose: you can read them on GitHub, and git stores the
changes cheaply when the scheduled job commits them after each run.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .util import iso, parse_time, utcnow

TABLES = ("estimates", "decisions", "orders", "claude_costs", "outcomes", "equity", "postmortems",
          "watch_decisions", "watch_signals")
# The data watcher (bot/watcher.py) runs on a separate server and writes only its own
# watch_* files, so its git pushes never collide with the scheduled bot's. Its pretend bets
# (watch_decisions) are merged into rows["decisions"] here, so the shared simulated account,
# the results page and settlement all include them.


class Journal:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.rows = {name: self._load(name) for name in TABLES}
        self.rows["decisions"] = sorted(self.rows["decisions"] + self.rows["watch_decisions"],
                                        key=lambda r: r.get("ts") or "")
        state_path = self.dir / "state.json"
        self.state = json.loads(state_path.read_text()) if state_path.exists() else {}

    def _load(self, name: str) -> list[dict]:
        path = self.dir / f"{name}.jsonl"
        if not path.exists():
            return []
        out = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def append(self, name: str, row: dict) -> dict:
        row = {"ts": iso(utcnow()), **row}
        self.rows[name].append(row)
        if name == "watch_decisions":
            self.rows["decisions"].append(row)
        with open(self.dir / f"{name}.jsonl", "a") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
        return row

    def set_state(self, key: str, value) -> None:
        if value is None:
            self.state.pop(key, None)
        else:
            self.state[key] = value
        (self.dir / "state.json").write_text(json.dumps(self.state, indent=2))

    # ---- lookups --------------------------------------------------------------
    def latest_estimate(self, ticker: str) -> dict | None:
        for row in reversed(self.rows["estimates"]):
            if row.get("ticker") == ticker:
                return row
        return None

    def claude_spend_on(self, day: str, env: str | None = None) -> float:
        return sum(r.get("usd", 0.0) for r in self.rows["claude_costs"]
                   if r.get("ts", "").startswith(day) and (env is None or r.get("env") == env))

    def order_spend_on(self, env: str, day: str) -> float:
        return sum(r.get("spent", 0.0) for r in self.rows["orders"]
                   if r.get("env") == env and r.get("ts", "").startswith(day))

    def outcome(self, env: str, ticker: str) -> str | None:
        for row in reversed(self.rows["outcomes"]):
            if row.get("env") == env and row.get("ticker") == ticker:
                return row.get("result")
        return None

    def paper_positions(self) -> list[dict]:
        """Shadow-mode 'would have bought' trades whose market hasn't resolved yet."""
        open_rows = {}
        for row in self.rows["decisions"]:
            if row.get("env") == "shadow" and row.get("action", "").startswith("paper_buy"):
                if self.outcome("shadow", row["ticker"]) is None:
                    open_rows.setdefault(row["ticker"], row)
        return list(open_rows.values())

    def unresolved_closed_tickers(self, env: str, now: datetime) -> list[str]:
        seen, out = set(), []
        rows = self.rows["estimates"] + self.rows["decisions"]
        for row in rows:
            t = row.get("ticker")
            if row.get("env") != env or not t or t in seen:
                continue
            seen.add(t)
            close = parse_time(row.get("close_time"))
            if close and close < now and self.outcome(env, t) is None:
                out.append(t)
        return out
