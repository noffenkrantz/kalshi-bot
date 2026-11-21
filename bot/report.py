"""Scorecard: is Claude actually better than the market price?

Brier score = average of (forecast - outcome)^2, where outcome is 1 for YES and 0 for NO.
Lower is better. Always guessing 50% scores 0.25. The market price is the
benchmark: if Claude can't beat it, there is no edge to trade on.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .journal import Journal
from .kalshi import KalshiClient, KalshiError
from .runner import update_outcomes
from .strategy import order_fee
from .util import iso, parse_time

MIN_RESOLVED_FOR_VERDICT = 100


def _brier(pairs: list[tuple[float, float]]) -> float:
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def _pnl(count: float, price: float, won: bool, fee: float | None = None) -> float:
    fee = order_fee(price, count) if fee is None else fee
    return count * ((1.0 if won else 0.0) - price) - fee


def build_report(journal: Journal, clients: dict[str, KalshiClient], now: datetime,
                 min_edge: float = 0.05) -> str:
    for env, client in clients.items():
        try:
            update_outcomes(journal, client, env, now, limit=200)
        except KalshiError:
            pass

    out = [f"# Kalshi bot report - {iso(now)}", ""]
    verdict_data = None
    for env in ("shadow", "demo", "live"):
        ests = [e for e in journal.rows["estimates"] if e.get("env") == env]
        decisions = [d for d in journal.rows["decisions"] if d.get("env") == env]
        orders = [o for o in journal.rows["orders"] if o.get("env") == env]
        if not (ests or decisions or orders):
            continue
        out.append(f"## {env.upper()}")

        resolved = []
        for e in ests:
            result = journal.outcome(env, e["ticker"])
            if result and e.get("market_mid") is not None:
                resolved.append((e["prob_yes"], e["market_mid"], 1.0 if result == "yes" else 0.0))
        out.append(f"Forecasts: {len(ests)} made, {len(resolved)} resolved")
        if resolved:
            claude_b = _brier([(p, y) for p, _, y in resolved])
            market_b = _brier([(m, y) for _, m, y in resolved])
            better = "BETTER" if claude_b < market_b else "WORSE"
            out.append(f"Accuracy (Brier, lower is better): Claude {claude_b:.4f} vs market price {market_b:.4f} "
                       f"-> Claude is {better} than the market")
            disagree = [(p, m, y) for p, m, y in resolved if abs(p - m) >= min_edge]
            if disagree:
                closer = sum(1 for p, m, y in disagree if abs(p - y) < abs(m - y))
                out.append(f"When Claude disagreed with the market by {min_edge:.0%}+: Claude was closer "
                           f"{closer} of {len(disagree)} times")
            out.append("Calibration (when Claude says X%, how often is it YES?):")
            for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
                bucket = [(p, y) for p, _, y in resolved if lo <= p < lo + 0.2 or (lo == 0.8 and p == 1.0)]
                if bucket:
                    avg_p = sum(p for p, _ in bucket) / len(bucket)
                    rate = sum(y for _, y in bucket) / len(bucket)
                    out.append(f"  {lo:.0%}-{lo + 0.2:.0%}: {len(bucket):>3} forecasts, avg said {avg_p:.0%}, "
                               f"actually YES {rate:.0%}")
            if env == "shadow":
                verdict_data = (len(resolved), claude_b, market_b)

        # trades
        if env == "shadow":
            trades = [d for d in decisions if d.get("action", "").startswith("paper_buy")]
            label = "Paper trades (at real prices, assuming fills at the ask)"
            rows = [(d["ticker"], d["outcome"], d["count"], d["outcome_price"], None) for d in trades]
        else:
            trades = [o for o in orders if (o.get("fill_count") or 0) > 0]
            label = "Filled orders"
            rows = [(o["ticker"], o["outcome"], o["fill_count"], o["outcome_price"], o.get("fee")) for o in trades]
        pnl, settled, wins = 0.0, 0, 0
        for ticker, outcome, count, price, fee in rows:
            result = journal.outcome(env, ticker)
            if result:
                won = result == outcome
                pnl += _pnl(count, price, won, fee)
                settled += 1
                wins += int(won)
        out.append(f"{label}: {len(rows)} total, {settled} settled, {wins} won, P&L on settled ~${pnl:+.2f}")

        eq = [r for r in journal.rows["equity"] if r.get("env") == env]
        if len(eq) >= 2:
            out.append(f"Account value: ${eq[0]['equity']:,.2f} at first run -> ${eq[-1]['equity']:,.2f} now")
        out.append("")

    week_ago = iso(now - timedelta(days=7))
    total_cost = sum(r.get("usd", 0.0) for r in journal.rows["claude_costs"])
    week_cost = sum(r.get("usd", 0.0) for r in journal.rows["claude_costs"] if r.get("ts", "") >= week_ago)
    out.append(f"Claude API spend: ~${week_cost:.2f} in the last 7 days, ~${total_cost:.2f} all time")
    out.append("")

    out.append("## Verdict")
    if not verdict_data or verdict_data[0] < MIN_RESOLVED_FOR_VERDICT:
        n = verdict_data[0] if verdict_data else 0
        out.append(f"Not enough data yet: {n}/{MIN_RESOLVED_FOR_VERDICT} shadow forecasts have resolved. "
                   "Keep collecting before drawing conclusions.")
    else:
        n, cb, mb = verdict_data
        if cb < mb:
            out.append(f"On {n} resolved forecasts Claude is beating the market price ({cb:.4f} vs {mb:.4f}). "
                       "Encouraging, but not proof; keep watching it across more markets and weeks.")
        else:
            out.append(f"On {n} resolved forecasts Claude is NOT beating the market price ({cb:.4f} vs {mb:.4f}). "
                       "There's no edge to trade yet. Don't use real money; try changing which markets it focuses on.")
    open_halts = {k: v for k, v in journal.state.items() if k.startswith("halted:")}
    for k, v in open_halts.items():
        out.append(f"NOTE: {k.split(':', 1)[1]} mode is halted: {v.get('reason')}")
    return "\n".join(out)
