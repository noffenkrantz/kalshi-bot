"""Pinnacle vs Kalshi gap tracker. Simulated only: it never places an order.

    python -m bot gaps --probe    check the pinnapi key, what its data looks like, and which
                                  Kalshi games it can be matched to (uses about 5 requests)
    python -m bot gaps            one snapshot: compare prices, record simulated bets, score them

Pinnacle's odds (through pinnapi.com, key in the PINNAPI_KEY secret) with its margin removed
are treated as the fair price. When Kalshi sells an outcome for less than that by more than
[gaps] min_edge after Kalshi's fee, the tracker records a simulated bet. Each bet is scored
by its "closing line value": Pinnacle's last fair price before the game minus what we paid.
Positive on average means the gaps were real; that shows up long before wins and losses do.

Files (separate from the main bot's, so their git pushes never collide):
    data/gap_snaps.jsonl     every matched price pair, each snapshot
    data/gap_bets.jsonl      simulated bets
    data/gap_outcomes.jsonl  how those markets settled
    data/gap_state.json      pinnapi requests used today
    GAPS.md                  the report
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import time
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .kalshi import KalshiClient, KalshiError
from .strategy import fee_per_contract
from .util import iso, parse_time, to_float, utcnow

PINNAPI = "https://pinnapi.com"
SPORTS = {"soccer": 1, "tennis": 2, "basketball": 3, "hockey": 4, "football": 5, "baseball": 6,
          "rugby": 7, "mma": 8, "boxing": 9, "esports": 11}
DEFAULTS = {"sports": ["soccer", "basketball", "hockey", "tennis"], "daily_requests": 95, "min_edge": 0.03,
            "stake_usd": 10.0, "window_hours": 24, "min_minutes_before_start": 10, "match_score": 0.8,
            "skip_series": ["KXESOCCERGAME", "KXEBASKETBALLGAME", "KXEFOOTBALLGAME"]}
ET = ZoneInfo("America/New_York")      # Kalshi's tickers carry US Eastern dates and times
_MON = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("gaps") or {})}


# ==== pinnapi ===================================================================================
class PinnError(Exception):
    pass


class PinnAPI:
    """Small client for pinnapi.com. The key goes in a header, never in a URL, so it can't leak
    into error messages or logs."""

    def __init__(self, key: str, session: requests.Session | None = None, timeout: float = 30, sleep=time.sleep):
        self.key, self.timeout, self.sleep = key, timeout, sleep
        self.session = session or requests.Session()
        self.calls = 0

    def get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(2):
            self.calls += 1
            try:
                r = self.session.get(PINNAPI + path, params=params or {}, timeout=self.timeout,
                                     headers={"x-portal-apikey": self.key, "Accept": "application/json"})
            except requests.RequestException as e:
                raise PinnError(f"GET {path}: {type(e).__name__}") from None
            if r.status_code == 429 and attempt == 0:
                self.sleep(min(to_float(r.headers.get("Retry-After"), 30.0), 90.0))
                continue
            if r.status_code in (401, 403):
                raise PinnError(f"GET {path}: pinnapi rejected the key (HTTP {r.status_code}): {r.text[:200]}")
            if r.status_code >= 400:
                raise PinnError(f"GET {path}: HTTP {r.status_code}: {r.text[:300]}")
            try:
                return r.json()
            except ValueError:
                raise PinnError(f"GET {path}: not JSON: {r.text[:200]}") from None
        raise PinnError(f"GET {path}: rate limited twice")

    def health(self) -> dict:
        return self.get("/health")

    def prematch(self, sport_id: int) -> dict:
        """Every upcoming event of one sport, with its odds, in one request."""
        return self.get("/kit/v1/markets", {"sport_id": sport_id, "event_type": "prematch"})


def no_vig(odds: dict) -> dict:
    """Decimal odds -> probabilities with the bookmaker's margin removed (proportionally)."""
    inv = {k: 1 / v for k, v in odds.items() if v and v > 1}
    total = sum(inv.values())
    return {k: v / total for k, v in inv.items()} if total else {}


def pinnacle_games(payload: dict) -> list[dict]:
    """Full-game match-winner odds for each main event (skips corners, games and other side events)."""
    out = []
    for e in (payload or {}).get("events") or []:
        home, away = e.get("home") or "", e.get("away") or ""
        if e.get("parent_id") or _SIDE_EVENT.search(home) or _SIDE_EVENT.search(away):
            continue
        periods = e.get("periods") or {}
        game = periods.get("num_0") if isinstance(periods, dict) else None
        ml = (game or {}).get("money_line") or {}
        odds = {k: to_float(ml.get(k)) for k in ("home", "draw", "away")}
        odds = {k: v for k, v in odds.items() if v is not None and v > 1}
        if "home" not in odds or "away" not in odds:
            continue
        starts = parse_time(e.get("starts"))
        if starts is None and e.get("start_ts"):
            starts = datetime.fromtimestamp(int(e["start_ts"]), timezone.utc)
        if starts is None:
            continue
        out.append({"id": e.get("event_id"), "league": e.get("league_name") or "", "home": home, "away": away,
                    "starts": starts, "odds": odds, "fair": no_vig(odds)})
    return out


# ==== Kalshi ====================================================================================
def game_series(root: Path, skip=()) -> list[str]:
    """Kalshi's sports match-winner series, from the market survey."""
    try:
        rows = json.load(open(root / "data" / "niche_survey.json"))["series"]
    except (OSError, ValueError, KeyError):
        return []
    return sorted(r["series"] for r in rows if r.get("category") == "Sports"
                  and r["series"].endswith(("GAME", "MATCH")) and r["series"] not in skip)


def event_when(event_ticker: str) -> tuple[date, datetime | None] | None:
    """KXELHGAME-26NOV221030HCEHCSK -> (2026-11-22, 10:30 US Eastern); the time is optional."""
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})(\d{4})?", event_ticker or "")
    if not m or m.group(2) not in _MON:
        return None
    try:
        d = date(2000 + int(m.group(1)), _MON[m.group(2)], int(m.group(3)))
    except ValueError:
        return None
    t = None
    if m.group(4):
        hh, mm = int(m.group(4)[:2]), int(m.group(4)[2:])
        if hh < 24 and mm < 60:
            t = datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET).astimezone(timezone.utc)
    return d, t


def outcome_name(m: dict) -> str:
    name = (m.get("yes_sub_title") or m.get("title") or "").strip()
    return re.sub(r"\s+wins\??$", "", name, flags=re.I).strip()


def is_tie(m: dict) -> bool:
    return (m.get("ticker") or "").upper().endswith("-TIE") or outcome_name(m).lower() in ("tie", "draw", "draw/tie")


def kalshi_games(kalshi: KalshiClient, series: list[str], say=print) -> list[dict]:
    events = []
    for s in series:
        try:
            ms = list(kalshi.iter_markets(max_markets=1000, series_ticker=s, status="open"))
        except KalshiError as e:
            say(f"  {s}: {str(e)[:120]}")
            continue
        by_ev = defaultdict(list)
        for m in ms:
            by_ev[m.get("event_ticker")].append(m)
        for ev, group in by_ev.items():
            when = event_when(ev)
            if not when:
                continue
            events.append({"event": ev, "series": s, "day": when[0], "time": when[1], "markets": group,
                           "teams": [outcome_name(m) for m in group if not is_tie(m)],
                           "has_tie": any(is_tie(m) for m in group)})
    return events


# ==== matching ==================================================================================
_STOP = {"fc", "cf", "sc", "afc", "club", "the", "cd", "fk", "sk", "if", "bk", "hc", "hk", "kk", "de",
         "w", "women", "womens", "u19", "u20", "u21", "u23"}
_SIDE_EVENT = re.compile(r"\((corners|bookings|cards|games|sets|points|hits|kills|maps|rounds|fouls|offsides)", re.I)


def tokens(name: str) -> list[str]:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", "").replace("st.", "saint ").replace("utd", "united")     # 'A&M' -> 'am'
    s = re.sub(r"^reg time:\s*", "", s)
    return [t for t in re.split(r"[^a-z0-9]+", s) if t and t not in _STOP]


def _same_token(t: str, u: str) -> bool:
    """t is a word of the shorter name, u of the longer."""
    if t == u:
        return True
    if len(t) == 1:                                      # an initial in the shorter name: 'T.' = 'Teodor'
        return u[0] == t
    if len(u) == 1:                                      # a stray letter in the longer name proves nothing
        return False
    if min(len(t), len(u)) >= 3 and (t.startswith(u) or u.startswith(t)):     # 'Giants' / 'G...' prefixes
        return True
    return min(len(t), len(u)) >= 5 and SequenceMatcher(None, t, u).ratio() >= 0.85   # spelling variants


def name_score(a: str, b: str) -> float:
    """1.0 = same team or player. Every word of the shorter name must match a word of the longer:
    'Davidov T.' = 'Teodor Davidov', 'Iserlohn' = 'Iserlohn Roosters', but 'Manchester United'
    vs 'Manchester City' or 'AC Milan' vs 'Inter Milan' only score 0.5."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(short) == 1 and len(short[0]) <= 2:      # a lone initial or code proves nothing
        return 0.0
    if len(short) == len(long_):                         # same length: let initials go either way
        overlap = max(sum(any(_same_token(t, u) for u in y) for t in x) / len(x) for x, y in ((ta, tb), (tb, ta)))
    else:
        overlap = sum(any(_same_token(t, u) for u in long_) for t in short) / len(short)
    ratio = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    return round(max(overlap * 0.98, ratio if ratio >= 0.92 else 0.0), 3)


def match(kev: dict, pin: list[dict], min_score: float) -> tuple[dict, dict, float] | None:
    """Best Pinnacle event for one Kalshi event: both teams must match and the start time fit.
    Returns (pinnacle event, {kalshi team name: 'home'|'away'}, score)."""
    if len(kev["teams"]) != 2:
        return None
    a, b = kev["teams"]
    best = None
    for p in pin:
        if kev["time"] is not None:
            gap_h = abs((p["starts"] - kev["time"]).total_seconds()) / 3600
            if gap_h > 3:
                continue
        else:
            d = p["starts"].astimezone(ET).date()
            gap_h = abs((d - kev["day"]).days) * 24
            if gap_h > 24:
                continue
        straight = min(name_score(a, p["home"]), name_score(b, p["away"]))
        swapped = min(name_score(a, p["away"]), name_score(b, p["home"]))
        score, sides = (straight, {a: "home", b: "away"}) if straight >= swapped else (swapped, {a: "away", b: "home"})
        if score >= min_score and (best is None or (score, -gap_h) > (best[2], -best[3])):
            best = (p, sides, score, gap_h)
    return best[:3] if best else None


def pairs(kev: dict, p: dict, sides: dict) -> tuple[list[tuple[dict, float]], str | None]:
    """(Kalshi market, Pinnacle fair chance of YES) for each outcome, or why they can't be compared."""
    three_way = "draw" in p["fair"]
    if kev["has_tie"] != three_way:
        return [], "Kalshi has a tie market but Pinnacle doesn't (or the reverse): rules differ"
    out = []
    for m in kev["markets"]:
        key = "draw" if is_tie(m) else sides.get(outcome_name(m))
        if key in p["fair"]:
            out.append((m, p["fair"][key]))
    return out, None


def edges(fair: float, bid: float | None, ask: float | None) -> dict:
    """Expected profit per contract after Kalshi's fee if Pinnacle is right, for buying YES at the
    ask or NO at (1 - bid)."""
    out = {}
    if ask is not None and 0 < ask < 1:
        out["yes"] = (ask, fair - ask - fee_per_contract(ask))
    if bid is not None and 0 < bid < 1:
        out["no"] = (1 - bid, (1 - fair) - (1 - bid) - fee_per_contract(1 - bid))
    return out


# ==== storage ===================================================================================
def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def append_jsonl(path: Path, rows: list[dict]) -> None:
    if rows:
        with open(path, "a") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")


def budget(data: Path, now: datetime, limit: int) -> tuple[dict, int]:
    path = data / "gap_state.json"
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    day = now.strftime("%Y-%m-%d")
    if state.get("day") != day:
        state = {"day": day, "calls": 0}
    return state, max(0, limit - state["calls"])


def save_budget(data: Path, state: dict, used: int) -> None:
    state["calls"] = state.get("calls", 0) + used
    (data / "gap_state.json").write_text(json.dumps(state) + "\n")


# ==== one snapshot ==============================================================================
def snapshot(kalshi: KalshiClient, pinn: PinnAPI, root: Path, cfg: dict, now: datetime | None = None,
             say=print) -> dict:
    g = settings(cfg)
    now = now or utcnow()
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    state, left = budget(data, now, int(g["daily_requests"]))
    sports = [s for s in g["sports"] if s in SPORTS][:left]
    if len(sports) < len(g["sports"]):
        say(f"pinnapi: {left} requests left today, checking {sports or 'nothing'}")
    pin, calls_before = [], pinn.calls
    for s in sports:
        try:
            pin += pinnacle_games(pinn.prematch(SPORTS[s]))
        except PinnError as e:
            say(f"pinnapi {s}: {e}")
    save_budget(data, state, pinn.calls - calls_before)
    horizon = now + timedelta(hours=float(g["window_hours"]))
    pin = [p for p in pin if now < p["starts"] <= horizon]
    say(f"Pinnacle: {len(pin)} games starting in the next {g['window_hours']}h ({', '.join(sports)})")

    kev = kalshi_games(kalshi, game_series(root, g["skip_series"]), say=say)
    bets_so_far = read_jsonl(data / "gap_bets.jsonl")
    have = {(b["ticker"], b["side"]) for b in bets_so_far}
    snaps, bets, matched, rules_differ = [], [], 0, 0
    for k in kev:
        hit = match(k, pin, float(g["match_score"]))
        if not hit:
            continue
        p, sides, score = hit
        prs, why = pairs(k, p, sides)
        if why:
            rules_differ += 1
            continue
        matched += 1
        mins = (p["starts"] - now).total_seconds() / 60
        for m, fair in prs:
            bid, ask = to_float(m.get("yes_bid_dollars")), to_float(m.get("yes_ask_dollars"))
            snaps.append({"ts": iso(now), "ticker": m["ticker"], "league": p["league"], "fair": round(fair, 4),
                          "bid": bid, "ask": ask, "vol24": round(to_float(m.get("volume_24h_fp"), 0.0))})
            if mins < float(g["min_minutes_before_start"]):
                continue
            for side, (price, edge) in edges(fair, bid, ask).items():
                if edge < float(g["min_edge"]) or not 0.05 <= price <= 0.95 or (m["ticker"], side) in have:
                    continue
                n = math.floor(float(g["stake_usd"]) / price)
                bets.append({"ts": iso(now), "ticker": m["ticker"], "event": k["event"], "series": k["series"],
                             "league": p["league"], "team": outcome_name(m), "side": side, "price": round(price, 4),
                             "fair": round(fair if side == "yes" else 1 - fair, 4), "edge": round(edge, 4),
                             "contracts": n, "starts": iso(p["starts"]), "pin_id": p["id"],
                             "pin_teams": f"{p['home']} vs {p['away']}"})
                have.add((m["ticker"], side))
    append_jsonl(data / "gap_snaps.jsonl", snaps)
    append_jsonl(data / "gap_bets.jsonl", bets)
    settled = settle(kalshi, data, now)
    say(f"Kalshi: {len(kev)} open games; {matched} matched to Pinnacle ({rules_differ} skipped: rules differ); "
        f"{len(snaps)} prices compared; {len(bets)} new simulated bets; {settled} bets settled")
    for b in bets:
        say(f"  bet {b['side'].upper()} {b['team']} ({b['league']}) at {b['price']:.2f}, Pinnacle fair "
            f"{b['fair']:.2f}, edge {b['edge'] * 100:+.1f}¢")
    write_report(root)
    return {"pinnacle_games": len(pin), "kalshi_games": len(kev), "matched": matched, "snaps": len(snaps),
            "bets": len(bets), "settled": settled}


def settle(kalshi: KalshiClient, data: Path, now: datetime) -> int:
    """Record results of simulated bets whose games ended (checked from 3 hours after the start)."""
    done = {o["ticker"] for o in read_jsonl(data / "gap_outcomes.jsonl")}
    due = sorted({b["ticker"] for b in read_jsonl(data / "gap_bets.jsonl")
                  if b["ticker"] not in done and (parse_time(b["starts"]) or now) < now - timedelta(hours=3)})
    rows = []
    for t in due[:60]:
        try:
            m = kalshi.request("GET", f"/markets/{t}").get("market") or {}
        except KalshiError:
            continue
        if m.get("result") in ("yes", "no"):
            rows.append({"ts": iso(now), "ticker": t, "result": m["result"]})
    append_jsonl(data / "gap_outcomes.jsonl", rows)
    return len(rows)


# ==== scoring and report ========================================================================
def score_bets(data: Path) -> list[dict]:
    """Each simulated bet with its closing line value and (when known) result."""
    snaps = defaultdict(list)
    for s in read_jsonl(data / "gap_snaps.jsonl"):
        snaps[s["ticker"]].append(s)
    results = {o["ticker"]: o["result"] for o in read_jsonl(data / "gap_outcomes.jsonl")}
    out = []
    for b in read_jsonl(data / "gap_bets.jsonl"):
        start = parse_time(b["starts"])
        before = [s for s in snaps.get(b["ticker"], []) if parse_time(s["ts"]) < start and s["ts"] > b["ts"]]
        close = before[-1] if before else None
        r = dict(b)
        if close:
            fair_close = close["fair"] if b["side"] == "yes" else 1 - close["fair"]
            r["close_fair"] = round(fair_close, 4)
            r["clv"] = round(fair_close - b["price"], 4)            # > 0: we paid less than Pinnacle's final number
            mid = lambda s: (s["bid"] + s["ask"]) / 2 if s.get("bid") is not None and s.get("ask") is not None else None
            entry = next((s for s in snaps[b["ticker"]] if s["ts"] == b["ts"]), None)
            if entry and mid(entry) is not None and mid(close) is not None:
                move = mid(close) - mid(entry)
                r["kalshi_move"] = round(move if b["side"] == "yes" else -move, 4)   # > 0: Kalshi came our way
                r["pinnacle_move"] = round((close["fair"] - entry["fair"]) * (1 if b["side"] == "yes" else -1), 4)
        res = results.get(b["ticker"])
        if res:
            won = res == b["side"]
            fee = fee_per_contract(b["price"])
            r["result"] = res
            r["profit"] = round(b["contracts"] * ((1 - b["price"]) if won else -b["price"]) - b["contracts"] * fee, 2)
        out.append(r)
    return out


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def _c(x):
    return "–" if x is None else f"{x * 100:+.1f}¢"


def _tight(s: dict) -> bool:
    return s.get("bid") is not None and s.get("ask") is not None and 0 < s["bid"] < s["ask"] < 1 and s["ask"] - s["bid"] <= 0.10


def _mid(s: dict) -> float:
    return (s["bid"] + s["ask"]) / 2


def _share_edge(snaps: list[dict], at: float = 0.03) -> float:
    if not snaps:
        return 0.0
    return sum(max((e for _, e in edges(s["fair"], s["bid"], s["ask"]).values()), default=-1) >= at for s in snaps) / len(snaps)


def write_report(root: Path) -> str:
    data = root / "data"
    snaps = read_jsonl(data / "gap_snaps.jsonl")
    bets = score_bets(data)
    runs = sorted({s["ts"] for s in snaps})
    lines = ["# Pinnacle vs Kalshi: gap tracker", "",
             f"*Simulated only, nothing is traded. {len(runs)} snapshots"
             + (f" from {runs[0][:16].replace('T', ' ')} to {runs[-1][:16].replace('T', ' ')} UTC" if runs else "")
             + ". Fair price = Pinnacle's odds with its margin removed. Edge = what a contract is worth at that "
             "price minus what Kalshi charges for it, after Kalshi's fee. Closing value = Pinnacle's last fair price "
             "before the game minus what we paid: positive on average means the gaps were real.*", ""]
    scored = [b for b in bets if b.get("clv") is not None]
    settled = [b for b in bets if b.get("profit") is not None]
    quoted = [s for s in snaps if _tight(s)]
    if snaps:
        lines += ["## Bottom line", "",
                  f"{len(snaps):,} Kalshi prices compared with Pinnacle's. {100 * len(quoted) / len(snaps):.0f}% had a real "
                  f"market (buy and sell prices within 10¢); in those, Kalshi's midpoint was {_c(_mean(abs(_mid(s) - s['fair']) for s in quoted))} "
                  f"from Pinnacle's fair price on average, and {100 * _share_edge(quoted):.1f}% could be bought at a 3¢+ edge "
                  "after fees.", ""]
    if bets:
        lines += [
                  f"{len(bets)} simulated bets so far; {len(scored)} have a closing price. Average edge when placed "
                  f"{_c(_mean(b['edge'] for b in bets))}; average closing value {_c(_mean(b.get('clv') for b in scored))}"
                  f" per contract. Kalshi moved toward Pinnacle's price after "
                  f"{sum((b.get('kalshi_move') or 0) > 0 for b in scored)} of them and Pinnacle moved toward Kalshi's after "
                  f"{sum((b.get('pinnacle_move') or 0) < 0 for b in scored)}. "
                  + (f"{len(settled)} have settled: {sum(b['result'] == b['side'] for b in settled)} won, simulated profit "
                     f"${sum(b['profit'] for b in settled):+,.2f} on ${sum(b['contracts'] * b['price'] for b in settled):,.0f} staked."
                     if settled else "None have settled yet."), ""]
    # by league
    per = defaultdict(lambda: {"snaps": [], "bets": []})
    for s in snaps:
        per[s["league"]]["snaps"].append(s)
    for b in bets:
        per[b["league"]]["bets"].append(b)
    lines += ["## By league", "",
              "*No real market* = buy and sell prices more than 10¢ apart (nobody quoting tightly: room to post orders). "
              "The gap and edge columns use only the prices with a real market.", "",
              "| League | Prices compared | No real market | Avg gap (Kalshi mid vs fair) | With a 3¢+ edge | Kalshi volume (24h, median) | Bets | Avg closing value | Profit |",
              "|---|---|---|---|---|---|---|---|---|"]
    rows = []
    for lg, d in per.items():
        ss = [s for s in d["snaps"] if _tight(s)]
        vol = statistics.median(s.get("vol24") or 0 for s in d["snaps"]) if d["snaps"] else 0
        prof = [b["profit"] for b in d["bets"] if b.get("profit") is not None]
        rows.append((len(d["snaps"]), f"| {lg} | {len(d['snaps'])} | {100 * (1 - len(ss) / len(d['snaps'])):.0f}% | "
                     f"{_c(_mean(abs(_mid(s) - s['fair']) for s in ss))} | {100 * _share_edge(ss):.0f}% | "
                     f"{vol:,.0f} | {len(d['bets'])} | {_c(_mean(b.get('clv') for b in d['bets']))} | "
                     + (f"${sum(prof):+,.2f}" if prof else "–") + " |"))
    lines += [r for _, r in sorted(rows, reverse=True)[:60]]
    if bets:
        lines += ["", "## Latest simulated bets", "",
                  "| Placed (UTC) | Game | Bet | Paid | Fair | Edge | Closing value | Result |", "|---|---|---|---|---|---|---|---|"]
        for b in sorted(bets, key=lambda b: b["ts"], reverse=True)[:30]:
            res = "–" if b.get("profit") is None else f"{'won' if b['result'] == b['side'] else 'lost'} ${b['profit']:+.2f}"
            lines.append(f"| {b['ts'][5:16].replace('T', ' ')} | {b['pin_teams']} ({b['league']}) | {b['side'].upper()} "
                         f"{b['team']} | {b['price']:.2f} | {b['fair']:.2f} | {_c(b['edge'])} | {_c(b.get('clv'))} | {res} |")
    lines.append("")
    text = "\n".join(lines)
    (root / "GAPS.md").write_text(text)
    return text


# ==== probe =====================================================================================
def probe(kalshi: KalshiClient, pinn: PinnAPI, root: Path, cfg: dict, say=print) -> int:
    g = settings(cfg)
    try:
        h = pinn.health()
        say(f"pinnapi health: {json.dumps(h)[:600]}")
    except PinnError as e:
        say(f"pinnapi health check failed: {e}")
        return 1
    pin = []
    for s in g["sports"]:
        try:
            payload = pinn.prematch(SPORTS[s])
        except PinnError as e:
            say(f"\n## {s}: {e}")
            continue
        events = payload.get("events") or []
        games = pinnacle_games(payload)
        pin += games
        say(f"\n## {s}: response keys {sorted(payload)[:12]}; {len(events)} events, {len(games)} with match-winner odds")
        if events:
            e = events[0]
            say(f"   event keys: {sorted(e)}")
            say(f"   sample: {json.dumps(e)[:1500]}")
        leagues = defaultdict(int)
        for x in games:
            leagues[x["league"]] += 1
        say("   leagues: " + "; ".join(f"{k} ({v})" for k, v in sorted(leagues.items(), key=lambda kv: -kv[1])[:40]))
    say(f"\npinnapi requests used: {pinn.calls}")
    kev = kalshi_games(kalshi, game_series(root, g["skip_series"]), say=say)
    by_series = defaultdict(lambda: [0, 0, 0, []])
    for k in kev:
        row = by_series[k["series"]]
        row[0] += 1
        hit = match(k, pin, float(g["match_score"]))
        if hit:
            p, sides, score = hit
            prs, why = pairs(k, p, sides)
            row[1 if not why else 2] += 1
            if len(row[3]) < 2:
                m = prs[0] if prs else None
                row[3].append(f"{' / '.join(k['teams'])} = {p['home']} vs {p['away']} ({p['league']}, {score})"
                              + (f"; {outcome_name(m[0])} Kalshi {m[0].get('yes_bid_dollars')}-{m[0].get('yes_ask_dollars')} "
                                 f"vs fair {m[1]:.2f}" if m else f"; {why}"))
    say(f"\n## Kalshi: {len(kev)} open games in {len(by_series)} series")
    for s, (n, ok, differ, ex) in sorted(by_series.items(), key=lambda kv: -kv[1][1]):
        say(f"   {s}: {n} games, {ok} matched, {differ} rules differ" + (f" | e.g. {' | '.join(ex)}" if ex else ""))
    rules = {}
    for k in kev:
        if k["series"] not in rules and k["markets"]:
            rules[k["series"]] = (k["markets"][0].get("rules_primary") or "")[:260]
    say("\n## Kalshi rules (first market of each series)")
    for s, r in sorted(rules.items()):
        say(f"   {s}: {r}")
    return 0


def main(cfg: dict, root: Path, probe_only: bool = False, say=print) -> int:
    key = os.environ.get("PINNAPI_KEY")
    if not key:
        say("PINNAPI_KEY is not set: add it as a repository secret (Settings > Secrets and variables > Actions).")
        return 0
    kalshi, pinn = KalshiClient("prod"), PinnAPI(key)
    if probe_only:
        return probe(kalshi, pinn, root, cfg, say=say)
    snapshot(kalshi, pinn, root, cfg, say=say)
    return 0
