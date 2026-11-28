"""Live mode of the gap tracker: [gaps] mode = "live". Needs a paid pinnapi plan (the free trial's
100 requests a day only allow hourly snapshots). Simulated only: it never places an order.

Runs inside the Render server (bot/server.py), which calls tick() about once a second:
  - every poll_seconds it asks pinnapi for the Pinnacle odds that changed since the last ask (one
    request per sport). When a paired game's fair price moves, it reads that game's Kalshi prices at
    once (one Kalshi request) and records a simulated bet if Kalshi is now cheaper than the fair
    price by [gaps] min_edge or more after Kalshi's fee.
  - moves of move_points or more are logged with Kalshi's price just before, right after, and 5 s,
    15 s, 1 min and 5 min later (data/gap_moves.jsonl): how fast Kalshi catches up with Pinnacle.
  - every 10 minutes it writes data/gap_live_status.json (is it polling, how many games are paired,
    the last error), so the tracker can be checked from the repo.
  - every kalshi_sweep_seconds it re-reads Kalshi's prices for all paired games, because Kalshi can
    drift on its own too.
  - every rematch_minutes it re-pairs Kalshi and Pinnacle games (new games, finished ones).
  - every snapshot_minutes it writes the usual snapshot rows, so GAPS.md's league table keeps working.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

from .gaps import (SPORTS, PinnAPI, PinnError, append_jsonl, available_at, budget, edges, game_series, is_side_event,
                   is_tie, kalshi_games, match, name_index, outcome_name, pairs, parse_event, read_jsonl, save_budget,
                   settings, settle, size_bet, write_report)
from .kalshi import KalshiClient, KalshiError
from .util import iso, parse_time, to_float, utcnow

LIVE_DEFAULTS = {"poll_seconds": 5, "kalshi_sweep_seconds": 30, "rematch_minutes": 30, "snapshot_minutes": 60,
                 "move_points": 0.02}
FOLLOW_SECONDS = (5, 15, 60, 300)
MOVED = 0.005            # a fair-price change smaller than half a point is noise


def _mid(q) -> float | None:
    bid, ask = q if q else (None, None)
    if bid is None or ask is None or not 0 < bid < ask < 1:
        return None
    return round((bid + ask) / 2, 4)


class LiveGaps:
    def __init__(self, root: Path, cfg: dict, kalshi: KalshiClient, pinn: PinnAPI, clock=utcnow, say=print):
        self.root, self.data = Path(root), Path(root) / "data"
        self.data.mkdir(parents=True, exist_ok=True)
        self.kalshi, self.pinn, self.clock, self.say = kalshi, pinn, clock, say
        self.reload(cfg)
        now = clock()
        self.since: dict[str, object] = {}
        self.pin: dict = {}            # Pinnacle event id -> game (None while it's off the board)
        self.links: dict = {}          # Pinnacle event id -> {"kev": Kalshi event, "sides": {...}}
        self.by_ticker: dict = {}      # Kalshi ticker -> (Pinnacle event id, "home"/"away"/"draw")
        self.quotes: dict = {}         # Kalshi ticker -> (yes_bid, yes_ask)
        self.vol24: dict = {}
        self.pending: list[dict] = []  # Pinnacle moves waiting for their follow-up Kalshi prices
        bets = read_jsonl(self.data / "gap_bets.jsonl")
        self.have = {(b["ticker"], b["side"]) for b in bets}
        self.games_bet = {b.get("event") for b in bets}      # one bet per game
        self.open_bets = {b["ticker"]: b for b in bets if (parse_time(b["starts"]) or now) > now}
        self.written: dict = {}        # ticker -> last (fair, bid, ask) written for an open bet
        self.flagged: set = set()
        self.sweep_by_tickers = True
        self.slow: dict = {}           # sport -> next poll time, when pinnapi sends full lists instead of changes
        self.next = {"rematch": now, "poll": now, "sweep": now + timedelta(seconds=30),
                     "snapshot": now + timedelta(minutes=5), "settle": now + timedelta(minutes=10),
                     "report": now + timedelta(minutes=10)}
        self.calls_logged = 0
        self.last_page: datetime | None = None
        self.dirty, self.new_bets, self.new_results = False, 0, 0
        self.started, self.polls_ok, self.changes_seen, self.moves_logged, self.bets_placed = now, 0, 0, 0, 0
        self.last_poll_ok: datetime | None = None
        self.last_error: str | None = None
        self.next["status"] = now + timedelta(minutes=2)
        self.status_pushed = now

    def status(self, now: datetime) -> dict:
        return {"ts": iso(now), "mode": "live", "running_since": iso(self.started), "paired_games": len(self.links),
                "paired_prices": len(self.by_ticker), "polls_ok": self.polls_ok,
                "last_poll_ok": iso(self.last_poll_ok) if self.last_poll_ok else None, "pinnacle_changes_seen": self.changes_seen,
                "moves_logged": self.moves_logged, "moves_waiting": len(self.pending), "bets_placed": self.bets_placed,
                "pinnapi_requests": self.pinn.calls, "slowed_sports": sorted(s for s, t in self.slow.items() if t > now),
                "kalshi_batch_reads": self.sweep_by_tickers, "last_error": self.last_error,
                "settings": {k: self.g.get(k) for k in ("poll_seconds", "kalshi_sweep_seconds", "min_edge", "stake_usd",
                                                       "bankroll_usd", "move_points", "sports")}}

    def reload(self, cfg: dict) -> None:
        self.g = {**LIVE_DEFAULTS, **settings(cfg)}

    # ---- the loop ------------------------------------------------------------------------------
    def _due(self, name: str, now: datetime, every: timedelta) -> bool:
        if now >= self.next[name]:
            self.next[name] = now + every
            return True
        return False

    def tick(self) -> None:
        now = self.clock()
        g = self.g
        try:
            if self._due("rematch", now, timedelta(minutes=float(g["rematch_minutes"]))):
                self.rematch(now)
            if self.links and self._due("poll", now, timedelta(seconds=float(g["poll_seconds"]))):
                self.poll(now)
        except PinnError as e:
            self.last_error = f"{iso(now)} pinnapi: {str(e)[:200]}"
            wait = 60 if "day" not in str(e) else 3600
            self.say(f"pinnapi: {e}; pausing {wait // 60} min" + (" (daily limit: live mode needs a paid plan)"
                                                                     if wait == 3600 else ""))
            self.next["poll"] = now + timedelta(seconds=wait)
            if not self.links:
                self.next["rematch"] = now + timedelta(seconds=wait)
        try:
            self.follow_up(now)
            if self._due("sweep", now, timedelta(seconds=float(g["kalshi_sweep_seconds"]))):
                self.sweep(now)
            if self._due("snapshot", now, timedelta(minutes=float(g["snapshot_minutes"]))):
                self.snapshot_rows(now)
            if self._due("settle", now, timedelta(minutes=5)):
                found = settle(self.kalshi, self.data, now)
                if found:                                  # a result: show it now, not at the next report
                    self.dirty, self.new_results = True, self.new_results + found
                    self.next["report"] = now
        except KalshiError as e:
            self.last_error = f"{iso(now)} Kalshi: {str(e)[:200]}"
            self.say(f"Kalshi: {str(e)[:200]}")
        if self._due("status", now, timedelta(minutes=10)):
            import json
            (self.data / "gap_live_status.json").write_text(json.dumps(self.status(now), indent=1) + "\n")
            if now - self.status_pushed >= timedelta(minutes=30):     # check in at least every half hour
                self.dirty, self.status_pushed = True, now
        if self.dirty and self._due("report", now, timedelta(minutes=10)):
            write_report(self.root)
            from .gapsite import write_site
            page = self.last_page is None or now - self.last_page >= timedelta(minutes=60)
            write_site(self.root, {"gaps": self.g}, now, page=page)
            if page:
                self.last_page = now
            state, _ = budget(self.data, now, int(g["daily_requests"]))
            save_budget(self.data, state, self.pinn.calls - self.calls_logged, ran_at=now)
            self.calls_logged = self.pinn.calls

    # ---- pairing -----------------------------------------------------------------------------
    def rematch(self, now: datetime) -> None:
        pin = {}
        for sport in self.g["sports"]:
            if sport not in SPORTS:
                continue
            payload = self.pinn.prematch(SPORTS[sport])
            self.since[sport] = payload.get("last")
            for e in payload.get("events") or []:
                if not is_side_event(e):
                    game = parse_event(e)
                    if game:
                        pin[game["id"]] = game
        horizon = now + timedelta(hours=float(self.g["window_hours"]))
        games = [x for x in pin.values() if now < x["starts"] <= horizon]
        links, by_ticker = {}, {}
        idx = name_index(games)
        for k in kalshi_games(self.kalshi, game_series(self.root, self.g["skip_series"]), say=self.say):
            hit = match(k, games, float(self.g["match_score"]), idx)
            if not hit:
                continue
            p, sides, _ = hit
            prs, why = pairs(k, p, sides)
            if why or not prs:
                continue
            links[p["id"]] = {"kev": k, "sides": sides}
            for m, _fair in prs:
                by_ticker[m["ticker"]] = (p["id"], "draw" if is_tie(m) else sides.get(outcome_name(m)))
                self.quotes[m["ticker"]] = (to_float(m.get("yes_bid_dollars")), to_float(m.get("yes_ask_dollars")))
                self.vol24[m["ticker"]] = round(to_float(m.get("volume_24h_fp"), 0.0))
        self.pin.update(pin)
        self.links, self.by_ticker = links, by_ticker
        self.say(f"live gaps: {len(links)} Kalshi games paired with Pinnacle ({len(by_ticker)} prices), "
                 f"watching every {self.g['poll_seconds']} s")
        for pid in links:
            self.evaluate(pid, now)

    # ---- Pinnacle --------------------------------------------------------------------------
    def poll(self, now: datetime) -> None:
        for sport in list(self.since):
            if self.since[sport] is None or now < self.slow.get(sport, now):
                continue
            payload = self.pinn.get("/kit/v1/markets", {"sport_id": SPORTS[sport], "event_type": "prematch",
                                                        "since": self.since[sport]})
            if payload.get("last") is not None:
                self.since[sport] = payload["last"]
            events = payload.get("events") or []
            self.polls_ok += 1
            self.last_poll_ok = now
            self.changes_seen += len(events)
            if len(events) > 300:                    # 'since' didn't narrow it: don't pull the whole list every few seconds
                if sport not in self.slow:
                    self.say(f"pinnapi sent all {len(events)} {sport} events, not just changes: checking {sport} once a minute")
                self.slow[sport] = now + timedelta(seconds=60)
            for e in events:
                pid = e.get("event_id")
                if pid not in self.links or is_side_event(e):
                    continue
                new, old = parse_event(e), self.pin.get(pid)
                self.pin[pid] = new                  # None = off the board: no bets until it's back
                if new is None or old is None:
                    continue
                moved = max(abs(new["fair"].get(k, 0) - old["fair"].get(k, 0)) for k in new["fair"])
                if moved >= MOVED:
                    self.on_move(pid, old, new, now)

    def on_move(self, pid, old: dict, new: dict, now: datetime) -> None:
        link = self.links[pid]
        tickers = [t for t, (p, _) in self.by_ticker.items() if p == pid]
        before = {t: _mid(self.quotes.get(t)) for t in tickers}
        self.fetch_event(link["kev"]["event"])
        key = max(new["fair"], key=lambda k: abs(new["fair"][k] - old["fair"].get(k, 0)))
        if abs(new["fair"][key] - old["fair"].get(key, 0)) >= float(self.g["move_points"]):
            t = next((t for t in tickers if self.by_ticker[t][1] == key), None)
            if t:
                self.pending.append({"ts": iso(now), "ticker": t, "event": link["kev"]["event"], "pid": pid,
                                     "league": new["league"], "game": f"{new['home']} vs {new['away']}",
                                     "fair_before": round(old["fair"][key], 4), "fair_after": round(new["fair"][key], 4),
                                     "mid_before": before.get(t), "mid_at": _mid(self.quotes.get(t)), "after": {},
                                     "due": [now + timedelta(seconds=s) for s in FOLLOW_SECONDS]})
        self.evaluate(pid, now)

    def follow_up(self, now: datetime) -> None:
        fetched = set()
        for rec in list(self.pending):
            while rec["due"] and now >= rec["due"][0]:
                rec["due"].pop(0)
                if rec["event"] not in fetched:
                    self.fetch_event(rec["event"])
                    fetched.add(rec["event"])
                    self.evaluate(rec["pid"], now)
                sec = FOLLOW_SECONDS[len(FOLLOW_SECONDS) - len(rec["due"]) - 1]
                game = self.pin.get(rec["pid"])
                rec["after"][str(sec)] = {"mid": _mid(self.quotes.get(rec["ticker"])),
                                          "fair": round(game["fair"].get(self.by_ticker.get(rec["ticker"], (0, "?"))[1], 0), 4)
                                          if game else None}
            if not rec["due"]:
                row = {k: v for k, v in rec.items() if k not in ("due", "pid", "event")}
                append_jsonl(self.data / "gap_moves.jsonl", [row])
                self.moves_logged += 1
                self.pending.remove(rec)
                self.dirty = True

    # ---- Kalshi -----------------------------------------------------------------------------
    def fetch_event(self, event_ticker: str) -> list[dict]:
        ms = self.kalshi.request("GET", "/markets", params={"event_ticker": event_ticker, "limit": 100}).get("markets") or []
        for m in ms:
            self.quotes[m["ticker"]] = (to_float(m.get("yes_bid_dollars")), to_float(m.get("yes_ask_dollars")))
        return ms

    def sweep(self, now: datetime) -> None:
        tickers = list(self.by_ticker)
        changed = set()
        if self.sweep_by_tickers:
            for i in range(0, len(tickers), 100):
                batch = tickers[i:i + 100]
                ms = self.kalshi.request("GET", "/markets", params={"tickers": ",".join(batch), "limit": 1000}).get("markets") or []
                if any(m.get("ticker") not in set(batch) for m in ms):
                    self.sweep_by_tickers = False       # Kalshi ignored the filter: read by game instead
                    self.say("Kalshi ignored the tickers filter; re-reading prices game by game")
                    break
                for m in ms:
                    q = (to_float(m.get("yes_bid_dollars")), to_float(m.get("yes_ask_dollars")))
                    if q != self.quotes.get(m["ticker"]):
                        self.quotes[m["ticker"]] = q
                        changed.add(self.by_ticker[m["ticker"]][0])
        if not self.sweep_by_tickers:
            soon = sorted(self.links, key=lambda p: self.pin[p]["starts"] if self.pin.get(p) else now)[:40]
            for pid in soon:                            # the 40 games starting soonest, each sweep
                old = {t: self.quotes.get(t) for t, (p, _) in self.by_ticker.items() if p == pid}
                self.fetch_event(self.links[pid]["kev"]["event"])
                if any(self.quotes.get(t) != q for t, q in old.items()):
                    changed.add(pid)
        for pid in changed:
            self.evaluate(pid, now)

    # ---- deciding ----------------------------------------------------------------------------
    def evaluate(self, pid, now: datetime) -> None:
        game, link = self.pin.get(pid), self.links.get(pid)
        if not game or not link:
            return
        early = ((game["starts"] - now).total_seconds() / 60 >= float(self.g["min_minutes_before_start"])
                 and link["kev"]["event"] not in self.games_bet)
        best = None
        for t, (p, key) in self.by_ticker.items():
            if p != pid or key not in game["fair"]:
                continue
            fair = game["fair"][key]
            bid, ask = self.quotes.get(t, (None, None))
            if early:
                for side, (price, edge) in edges(fair, bid, ask).items():
                    if edge < float(self.g["min_edge"]) or not 0.05 <= price <= 0.95 or (t, side) in self.have:
                        continue
                    if edge > float(self.g["max_edge"]):
                        if (t, side) not in self.flagged:
                            self.flagged.add((t, side))
                            self.say(f"  skipped, edge too large to be real (check the match): {t} {side} at "
                                     f"{price:.2f} vs fair {fair:.2f} ({game['home']} vs {game['away']})")
                        continue
                    if best is None or edge > best[3]:
                        best = (t, side, price, edge, fair)
            if t in self.open_bets and now < game["starts"]:
                last = (round(fair, 4), bid, ask)
                if self.written.get(t) != last:          # keeps the closing price of every open bet
                    self.written[t] = last
                    append_jsonl(self.data / "gap_snaps.jsonl", [self.snap(t, fair, bid, ask, game, now)])
                    self.dirty = True
        if best:                                     # the single best side of this game
            t, side, price, edge, fair = best
            self.bet(t, side, price, fair, edge, game, link, now)

    def bet(self, t, side, price, fair, edge, game, link, now) -> None:
        m = next((x for x in link["kev"]["markets"] if x["ticker"] == t), {"ticker": t})
        row = {"ts": iso(now), "ticker": t, "event": link["kev"]["event"], "series": link["kev"]["series"],
               "league": game["league"], "team": outcome_name(m), "side": side, "price": round(price, 4),
               "fair": round(fair if side == "yes" else 1 - fair, 4), "edge": round(edge, 4),
               **size_bet(float(self.g["stake_usd"]), price, available_at(self.kalshi, t, side, price)),
               "starts": iso(game["starts"]),
               "pin_id": game["id"], "pin_teams": f"{game['home']} vs {game['away']}", "live": True}
        append_jsonl(self.data / "gap_bets.jsonl", [row])
        bid, ask = self.quotes.get(t, (None, None))
        append_jsonl(self.data / "gap_snaps.jsonl", [self.snap(t, fair, bid, ask, game, now)])   # the entry price
        self.written[t] = (round(fair, 4), bid, ask)
        self.have.add((t, side))
        self.games_bet.add(link["kev"]["event"])
        self.open_bets[t] = row
        self.dirty, self.new_bets = True, self.new_bets + 1
        self.bets_placed += 1
        self.say(f"  bet {side.upper()} {row['team']} ({game['league']}) at {price:.2f}, Pinnacle fair "
                 f"{row['fair']:.2f}, edge {edge * 100:+.1f}¢")

    def snap(self, t, fair, bid, ask, game, now) -> dict:
        return {"ts": iso(now), "ticker": t, "league": game["league"], "fair": round(fair, 4), "bid": bid, "ask": ask,
                "vol24": self.vol24.get(t, 0)}

    def snapshot_rows(self, now: datetime) -> None:
        """The hourly-style rows for every paired price, from what's already in memory (no requests)."""
        horizon = now + timedelta(hours=float(self.g["window_hours"]))
        rows = []
        for t, (pid, key) in self.by_ticker.items():
            game = self.pin.get(pid)
            if game and now < game["starts"] <= horizon and key in game["fair"]:
                bid, ask = self.quotes.get(t, (None, None))
                rows.append(self.snap(t, game["fair"][key], bid, ask, game, now))
        append_jsonl(self.data / "gap_snaps.jsonl", rows)
        if rows:
            self.dirty = True
