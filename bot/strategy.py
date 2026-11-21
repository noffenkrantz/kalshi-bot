"""The rules: is there enough edge after fees, and how much to buy within the limits.

This file is plain math. Claude never decides the size of a trade.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .util import to_float, valid_price

CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def fee_per_contract(price: float, rate: float = 0.07) -> float:
    return rate * price * (1 - price)


def order_fee(price: float, count: float, rate: float = 0.07) -> float:
    """Kalshi's general taker fee: round up(rate x C x P x (1-P)) to the next cent."""
    raw = rate * count * price * (1 - price)
    return math.ceil(round(raw * 100, 6)) / 100


@dataclass
class Quotes:
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    yes_bid_size: float | None
    yes_ask_size: float | None

    @property
    def mid(self) -> float | None:
        if valid_price(self.yes_bid) and valid_price(self.yes_ask):
            return (self.yes_bid + self.yes_ask) / 2
        return None

    @property
    def spread(self) -> float | None:
        if valid_price(self.yes_bid) and valid_price(self.yes_ask):
            return self.yes_ask - self.yes_bid
        return None


def quotes(market: dict) -> Quotes:
    yb = to_float(market.get("yes_bid_dollars"))
    ya = to_float(market.get("yes_ask_dollars"))
    nb = to_float(market.get("no_bid_dollars"))
    na = to_float(market.get("no_ask_dollars"))
    if na is None and yb is not None:
        na = round(1 - yb, 4)
    if nb is None and ya is not None:
        nb = round(1 - ya, 4)
    return Quotes(yb, ya, nb, na, to_float(market.get("yes_bid_size_fp")),
                  to_float(market.get("yes_ask_size_fp")))


@dataclass
class Account:
    bankroll: float = 0.0          # cash available for sizing
    exposure: float = 0.0          # money currently tied up in positions
    open_positions: int = 0
    spent_today: float = 0.0
    held_tickers: set = field(default_factory=set)


@dataclass
class Decision:
    ticker: str
    action: str                    # "skip", "buy_yes" or "buy_no"
    reason: str
    outcome: str | None = None     # "yes" or "no"
    book_side: str | None = None   # "bid" (buy YES) or "ask" (sell YES = buy NO)
    api_price: str | None = None   # price on the YES book, sent to Kalshi
    outcome_price: float | None = None  # what one contract of our side costs
    count: int = 0
    edge: float | None = None      # expected profit per contract after fees
    est_cost: float = 0.0          # contracts x price + fee


def skip(ticker: str, reason: str, edge: float | None = None) -> Decision:
    return Decision(ticker=ticker, action="skip", reason=reason, edge=edge)


def decide(market: dict, est: dict, strat: dict, risk: dict, acct: Account) -> Decision:
    """est needs prob_yes, confidence and rules_clear."""
    ticker = market["ticker"]
    if ticker in acct.held_tickers:
        return skip(ticker, "already holding a position here")
    if not est.get("rules_clear"):
        return skip(ticker, "Claude flagged the rules as unclear")
    conf = str(est.get("confidence", "low")).lower()
    if CONFIDENCE_RANK.get(conf, 0) < CONFIDENCE_RANK[strat["min_confidence"]]:
        return skip(ticker, f"confidence is {conf}")

    q = quotes(market)
    p = float(est["prob_yes"])
    rate = strat.get("fee_rate", 0.07)
    lo, hi = strat.get("min_buy_price", 0.05), strat.get("max_buy_price", 0.95)
    options = []
    if valid_price(q.yes_ask) and lo <= q.yes_ask <= hi:
        fee = fee_per_contract(q.yes_ask, rate)
        options.append(dict(outcome="yes", prob=p, price=q.yes_ask, fee=fee, edge=p - q.yes_ask - fee,
                            book_side="bid", api_price=market.get("yes_ask_dollars"), size=q.yes_ask_size))
    if valid_price(q.yes_bid) and valid_price(q.no_ask) and lo <= q.no_ask <= hi:
        fee = fee_per_contract(q.no_ask, rate)
        # Buying NO at no_ask is the same trade as selling YES at yes_bid.
        options.append(dict(outcome="no", prob=1 - p, price=q.no_ask, fee=fee, edge=(1 - p) - q.no_ask - fee,
                            book_side="ask", api_price=market.get("yes_bid_dollars"), size=q.yes_bid_size))
    if not options:
        return skip(ticker, "no tradeable price in range")
    best = max(options, key=lambda o: o["edge"])
    if best["edge"] < strat["min_edge"]:
        return skip(ticker, f"edge {best['edge']:+.3f} is below the {strat['min_edge']:.2f} minimum", best["edge"])

    if acct.open_positions >= risk["max_open_positions"]:
        return skip(ticker, "max open positions reached", best["edge"])
    cost_per = best["price"] + best["fee"]
    kelly = (best["prob"] - cost_per) / (1 - cost_per)
    dollars = min(
        acct.bankroll * strat["kelly_fraction"] * kelly,
        risk["max_dollars_per_trade"],
        risk["max_total_exposure"] - acct.exposure,
        risk["max_dollars_spent_per_day"] - acct.spent_today,
        acct.bankroll,
    )
    count = math.floor(max(dollars, 0) / cost_per)
    if best["size"] is not None:
        count = min(count, math.floor(best["size"]))
    if count < 1:
        return skip(ticker, "trade size rounds to zero under the current limits", best["edge"])

    return Decision(
        ticker=ticker, action=f"buy_{best['outcome']}",
        reason=f"Claude {p:.0%} YES vs price {best['price']:.2f} for {best['outcome'].upper()}",
        outcome=best["outcome"], book_side=best["book_side"], api_price=best["api_price"],
        outcome_price=best["price"], count=count, edge=round(best["edge"], 4),
        est_cost=round(count * best["price"] + order_fee(best["price"], count, rate), 2),
    )
