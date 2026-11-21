"""One run of the bot: safety checks -> account -> scan -> research -> decide -> trade."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .analyst import AnalystError, CostMeter, question_text, research_market
from .claude import ClaudeClient, ClaudeError
from .config import ROOT, effective_risk
from .journal import Journal
from .kalshi import KalshiClient, KalshiError
from .strategy import Account, Decision, decide, order_fee, quotes
from .util import iso, parse_time, to_float


class Summary:
    def __init__(self, title: str):
        self.title = title
        self.lines: list[str] = []

    def add(self, line: str) -> None:
        self.lines.append(line)
        print(line, flush=True)

    def markdown(self) -> str:
        return f"### {self.title}\n\n" + "\n".join(f"- {line}" for line in self.lines) + "\n"


def write_step_summary(markdown: str) -> None:
    """Shows the run summary on the GitHub Actions page when running there."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(markdown + "\n")


@dataclass
class Bot:
    mode: str                      # "shadow", "demo" or "live"
    cfg: dict
    data: KalshiClient             # where market data comes from
    trade: KalshiClient | None     # where orders go (None in shadow mode)
    claude: ClaudeClient | None
    journal: Journal
    now: datetime
    root: Path = ROOT
    summary: Summary = field(init=False)

    def __post_init__(self):
        self.summary = Summary(f"Kalshi bot - {self.mode} run - {self.now:%Y-%m-%d %H:%M} UTC")


# ---- safety -------------------------------------------------------------------
def safety_gate(bot: Bot) -> str | None:
    if (bot.root / "STOP").exists():
        return "a file named STOP exists in the project folder (delete it to resume)"
    if os.environ.get("BOT_DISABLED", "").lower() in ("1", "true", "yes"):
        return "BOT_DISABLED is set"
    halted = bot.journal.state.get(f"halted:{bot.mode}")
    if halted:
        return f"halted earlier: {halted.get('reason')} (run `python -m bot resume --mode {bot.mode}`)"
    if bot.mode == "live" and not (os.environ.get("ALLOW_REAL_MONEY") == "yes"
                                    and bot.cfg.get("live", {}).get("enabled") is True):
        return "live mode is locked (needs [live] enabled = true AND ALLOW_REAL_MONEY=yes)"
    return None


def halt(bot: Bot, reason: str) -> None:
    bot.journal.set_state(f"halted:{bot.mode}", {"reason": reason, "ts": iso(bot.now)})
    bot.summary.add(f"HALTED: {reason}")


# ---- outcomes -------------------------------------------------------------------
def update_outcomes(journal: Journal, client: KalshiClient, env: str, now: datetime,
                    limit: int = 40) -> int:
    found = 0
    for ticker in journal.unresolved_closed_tickers(env, now)[:limit]:
        try:
            market = client.get_market(ticker)
        except KalshiError:
            continue
        result = str(market.get("result") or "").lower()
        if result in ("yes", "no"):
            journal.append("outcomes", {"ts": iso(now), "env": env, "ticker": ticker, "result": result})
            found += 1
    return found


# ---- account --------------------------------------------------------------------
def real_account(bot: Bot, risk: dict, today: str) -> Account | None:
    bal = bot.trade.get_balance()
    cash = to_float(bal.get("balance_dollars"))
    if cash is None:
        cash = (bal.get("balance") or 0) / 100
    held, exposure, value = set(), 0.0, 0.0
    for pos in bot.trade.get_positions():
        n = to_float(pos.get("position_fp"), 0.0)
        if not n:
            continue
        ticker = pos.get("ticker")
        held.add(ticker)
        cost = to_float(pos.get("market_exposure_dollars"), 0.0)
        exposure += cost
        try:
            mid = quotes(bot.trade.get_market(ticker)).mid
        except KalshiError:
            mid = None
        value += cost if mid is None else (n * mid if n > 0 else -n * (1 - mid))
    equity = round(cash + value, 2)
    bot.journal.append("equity", {"ts": iso(bot.now), "env": bot.mode, "cash": round(cash, 2),
                                  "positions_value": round(value, 2), "equity": equity})
    peak_key = f"peak_equity:{bot.mode}"
    peak = max(float(bot.journal.state.get(peak_key) or 0), equity)
    bot.journal.set_state(peak_key, peak)
    bot.summary.add(f"Account: cash ${cash:,.2f}, positions ~${value:,.2f}, total ${equity:,.2f} "
                    f"(peak ${peak:,.2f}), {len(held)} open positions")
    if peak > 0 and equity < peak * (1 - risk["max_drawdown"]):
        halt(bot, f"account fell {1 - equity / peak:.0%} below its peak (limit {risk['max_drawdown']:.0%})")
        return None
    return Account(bankroll=cash, exposure=exposure, open_positions=len(held),
                   spent_today=bot.journal.order_spend_on(bot.mode, today), held_tickers=held)


def paper_account(bot: Bot, today: str) -> Account:
    open_rows = bot.journal.paper_positions()
    exposure = sum(r.get("est_cost", 0.0) for r in open_rows)
    spent = sum(r.get("est_cost", 0.0) for r in bot.journal.rows["decisions"]
                if r.get("env") == "shadow" and r.get("action", "").startswith("paper_buy")
                and r.get("ts", "").startswith(today))
    bankroll = float(bot.cfg.get("shadow", {}).get("paper_bankroll", 1000)) - exposure
    bot.summary.add(f"Paper account: ${max(bankroll, 0):,.2f} free, ${exposure:,.2f} in "
                    f"{len(open_rows)} open paper positions")
    return Account(bankroll=max(bankroll, 0.0), exposure=exposure, open_positions=len(open_rows),
                   spent_today=spent, held_tickers={r["ticker"] for r in open_rows})


# ---- market scan ----------------------------------------------------------------
def passes_filters(m: dict, f: dict, min_volume: float, now: datetime) -> bool:
    if m.get("market_type", "binary") != "binary":
        return False
    close = parse_time(m.get("close_time"))
    if not close:
        return False
    hours = (close - now).total_seconds() / 3600
    if hours < f["min_hours_to_close"] or hours > f["max_days_to_close"] * 24:
        return False
    q = quotes(m)
    if q.mid is None or not (f["min_price"] <= q.mid <= f["max_price"]):
        return False
    if q.spread is None or q.spread > f["max_spread"]:
        return False
    return to_float(m.get("volume_24h_fp"), 0.0) >= min_volume


def scan_markets(client: KalshiClient, f: dict, mode: str, now: datetime) -> list[dict]:
    min_volume = f["demo_min_volume_24h"] if mode == "demo" else f["min_volume_24h"]
    cap = int(f.get("max_markets_scanned", 10000))
    sources = [{"series_ticker": s} for s in f.get("include_series") or []] or [{}]
    found = {}
    for extra in sources:
        for m in client.iter_markets(max_markets=cap, status="open", mve_filter="exclude", **extra):
            if passes_filters(m, f, min_volume, now):
                found[m["ticker"]] = m
    return sorted(found.values(), key=lambda m: to_float(m.get("volume_24h_fp"), 0.0), reverse=True)


def is_fresh(est: dict | None, market: dict, bot: Bot) -> bool:
    if not est:
        return False
    ts = parse_time(est.get("ts"))
    if not ts:
        return False
    ccfg = bot.cfg["claude"]
    if (bot.now - ts).total_seconds() / 3600 > ccfg["reanalyze_after_hours"]:
        return False
    if est.get("env") == bot.mode:
        mid, old = quotes(market).mid, est.get("market_mid")
        if mid is not None and old is not None and abs(mid - old) >= ccfg["reanalyze_if_price_moves"]:
            return False
    return True


# ---- orders ---------------------------------------------------------------------
def place_and_verify(bot: Bot, m: dict, d: Decision, acct: Account) -> None:
    ticker, s = m["ticker"], bot.summary
    row = {"ts": iso(bot.now), "env": bot.mode, "ticker": ticker, "close_time": m.get("close_time"),
           "outcome": d.outcome, "book_side": d.book_side, "api_price": d.api_price,
           "outcome_price": d.outcome_price, "count": d.count, "edge": d.edge}
    try:
        resp = bot.trade.create_order(ticker, d.book_side, d.count, d.api_price)
    except KalshiError as e:
        row.update(status="rejected", note=str(e)[:300], spent=0.0)
        bot.journal.append("orders", row)
        s.add(f"Order rejected on {ticker}: {e}")
        if e.status == 410:
            halt(bot, "Kalshi says this order endpoint no longer exists; the code needs an update")
        return

    filled = to_float(resp.get("fill_count"), 0.0)
    fee_each = to_float(resp.get("average_fee_paid"))
    fee = round(fee_each * filled, 2) if fee_each is not None else (
        order_fee(d.outcome_price, filled) if filled else 0.0)
    spent = round(filled * d.outcome_price + fee, 2)
    row.update(order_id=resp.get("order_id"), client_order_id=resp.get("client_order_id"),
               fill_count=filled, remaining_count=resp.get("remaining_count"),
               average_fill_price=resp.get("average_fill_price"), fee=fee, spent=spent)

    # Self-check: confirm Kalshi recorded the direction we meant (YES vs NO).
    status = "placed"
    try:
        order = bot.trade.get_order(resp["order_id"]) if resp.get("order_id") else {}
        side = str(order.get("outcome_side") or "").lower()
        if side and side != d.outcome:
            status = "direction_mismatch"
            halt(bot, f"order {resp.get('order_id')} on {ticker} was recorded as {side.upper()} but the "
                      f"bot meant {d.outcome.upper()}. Check it on Kalshi before resuming.")
        else:
            status = order.get("status") or "placed"
            row["verified"] = bool(side)
    except KalshiError as e:
        row["note"] = f"could not verify: {e}"[:300]
    row["status"] = status
    bot.journal.append("orders", row)

    if filled > 0:
        acct.exposure += spent
        acct.spent_today += spent
        acct.bankroll -= spent
        acct.open_positions += 1
        acct.held_tickers.add(ticker)
        s.add(f"BOUGHT {filled:g} {d.outcome.upper()} on {ticker} at ${d.outcome_price:.2f} "
              f"(edge {d.edge:+.2f}/contract, cost ${spent:.2f})")
    else:
        s.add(f"Order on {ticker} didn't fill (the price moved), nothing bought")


# ---- main loop ------------------------------------------------------------------
def run_once(bot: Bot) -> Summary:
    s = bot.summary
    gate = safety_gate(bot)
    if gate:
        s.add(f"Not running: {gate}")
        return s

    cfg, ccfg, fcfg, strat = bot.cfg, bot.cfg["claude"], bot.cfg["filters"], bot.cfg["strategy"]
    risk = effective_risk(cfg, bot.mode)
    today = bot.now.strftime("%Y-%m-%d")

    try:
        n = update_outcomes(bot.journal, bot.data, bot.mode, bot.now)
        if n:
            s.add(f"Recorded {n} newly resolved market(s)")
    except KalshiError as e:
        s.add(f"Couldn't check resolved markets: {e}")

    can_trade = True
    if bot.trade:
        status = bot.trade.exchange_status()
        if not status.get("trading_active", False):
            s.add("Kalshi trading is paused right now; researching only")
            can_trade = False
        acct = real_account(bot, risk, today)
        if acct is None:
            return s
    else:
        acct = paper_account(bot, today)

    candidates = scan_markets(bot.data, fcfg, bot.mode, bot.now)
    s.add(f"{len(candidates)} markets passed the filters")

    budget_left = ccfg["daily_budget_usd"] - bot.journal.claude_spend_on(today, bot.mode)
    excluded = [c.lower() for c in fcfg.get("exclude_categories", [])]
    events: dict = {}
    new_forecasts = trades = considered = 0

    for m in candidates:
        if considered >= fcfg.get("max_candidates_considered", 40):
            break
        ticker = m["ticker"]
        ev_key = m.get("event_ticker")
        if ev_key not in events:
            try:
                events[ev_key] = bot.data.get_event(ev_key) if ev_key else {}
            except KalshiError:
                events[ev_key] = {}
        event = events[ev_key]
        category = str(event.get("category") or "").lower()
        if category and any(x in category for x in excluded):
            continue
        considered += 1

        est = bot.journal.latest_estimate(ticker)
        is_new = False
        if not is_fresh(est, m, bot):
            if bot.claude is None or new_forecasts >= ccfg["max_new_analyses_per_run"] or budget_left <= 0:
                continue
            meter = CostMeter()
            new_forecasts += 1
            try:
                e = research_market(bot.claude, ccfg, m, event, bot.now, meter)
            except (AnalystError, ClaudeError) as err:
                s.add(f"Research failed for {ticker}: {err}")
                continue
            finally:
                bot.journal.append("claude_costs", {"ts": iso(bot.now), "env": bot.mode, "ticker": ticker,
                                                    "usd": round(meter.total, 4)})
                budget_left -= meter.total
            q = quotes(m)
            est = bot.journal.append("estimates", {
                "ts": iso(bot.now), "env": bot.mode, "ticker": ticker,
                "event_ticker": m.get("event_ticker"), "question": question_text(m, event),
                "close_time": m.get("close_time"), "market_mid": q.mid, "yes_bid": q.yes_bid,
                "yes_ask": q.yes_ask, "prob_yes": e.probability_yes, "confidence": e.confidence,
                "rules_clear": e.rules_clear, "summary": e.resolution_summary,
                "evidence": e.key_evidence, "would_change_mind": e.would_change_my_mind,
                "red_flags": e.red_flags, "sources": e.sources, "model": e.model,
                "cost_usd": round(meter.total, 4)})
            is_new = True
            s.add(f"Forecast {ticker}: Claude {e.probability_yes:.0%} YES ({e.confidence}) vs market "
                  f"{q.mid:.0%} - {question_text(m, event)[:90]}")

        d = decide(m, est, strat, risk, acct)
        q = quotes(m)
        base = {"ts": iso(bot.now), "env": bot.mode, "ticker": ticker, "close_time": m.get("close_time"),
                "market_mid": q.mid, "prob_yes": est.get("prob_yes"), "edge": d.edge}
        if d.action == "skip":
            if is_new:
                bot.journal.append("decisions", {**base, "action": "skip", "reason": d.reason})
            continue
        if trades >= risk["max_trades_per_run"]:
            s.add(f"Trade limit for this run reached; not trading {ticker}")
            continue

        if bot.trade is None:  # shadow mode: record what it would have done, at real prices
            bot.journal.append("decisions", {**base, "action": f"paper_{d.action}", "reason": d.reason,
                                             "outcome": d.outcome, "outcome_price": d.outcome_price,
                                             "count": d.count, "est_cost": d.est_cost})
            acct.exposure += d.est_cost
            acct.spent_today += d.est_cost
            acct.bankroll -= d.est_cost
            acct.open_positions += 1
            acct.held_tickers.add(ticker)
            trades += 1
            s.add(f"Paper trade: would buy {d.count} {d.outcome.upper()} on {ticker} at "
                  f"${d.outcome_price:.2f} (edge {d.edge:+.2f}/contract, ~${d.est_cost:.2f})")
            continue

        if not can_trade:
            continue
        bot.journal.append("decisions", {**base, "action": d.action, "reason": d.reason,
                                         "outcome": d.outcome, "outcome_price": d.outcome_price,
                                         "count": d.count, "est_cost": d.est_cost})
        place_and_verify(bot, m, d, acct)
        trades += 1
        if bot.journal.state.get(f"halted:{bot.mode}"):
            break

    s.add(f"Done: {new_forecasts} new forecasts, {trades} {'paper ' if bot.trade is None else ''}trades. "
          f"Claude spend today ({bot.mode}) ~${bot.journal.claude_spend_on(today, bot.mode):.2f} "
          f"of ${ccfg['daily_budget_usd']:.2f}")
    return s
