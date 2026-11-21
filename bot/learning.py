"""Self-improvement, part 1: learn where Claude is good.

Every settled forecast is scored against the market price it was made at. Results are
grouped by topic (Kalshi's category for the event), by Claude's confidence, and by how far
Claude was from the market. The research budget then follows the results:

- 80% of new research goes to topics in proportion to how often Claude has beaten the
  market there (with a neutral starting assumption, so a few results can't swing it much).
- 20% is spread at random across whatever topics are available, so every topic keeps
  getting chances and an unlucky streak isn't the final word.
"""
from __future__ import annotations

import random
from collections import defaultdict

UNKNOWN_TOPIC = "Other"
DISAGREE_GAP = 0.05      # Claude and the market "disagree" when 5+ points apart
PRIOR = 2.0              # pretend each topic starts with 2 wins and 2 losses
SHARPNESS = 3.0          # how strongly the budget follows the win rate


def topic_for(row: dict, journal) -> str:
    return (row.get("category")
            or journal.state.get("event_categories", {}).get(row.get("event_ticker"))
            or UNKNOWN_TOPIC)


def settled_forecasts(journal, env: str = "shadow") -> list[dict]:
    out = []
    for e in journal.rows["estimates"]:
        if e.get("env") != env or e.get("market_mid") is None or e.get("prob_yes") is None:
            continue
        result = journal.outcome(env, e["ticker"])
        if result in ("yes", "no"):
            out.append({**e, "y": 1.0 if result == "yes" else 0.0, "topic": topic_for(e, journal)})
    return out


def distance_bucket(r: dict) -> str:
    gap = abs(r["prob_yes"] - r["market_mid"])
    if gap < 0.05:
        return "within 5 pts of market"
    if gap < 0.15:
        return "5–15 pts from market"
    return "15+ pts from market"


def group_stats(rows: list[dict], key) -> dict[str, dict]:
    groups: dict = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    out = {}
    for name, rs in groups.items():
        disagreements = [r for r in rs if abs(r["prob_yes"] - r["market_mid"]) >= DISAGREE_GAP]
        wins = sum(1 for r in disagreements if abs(r["prob_yes"] - r["y"]) < abs(r["market_mid"] - r["y"]))
        out[name] = {
            "n": len(rs),
            "claude_brier": sum((r["prob_yes"] - r["y"]) ** 2 for r in rs) / len(rs),
            "market_brier": sum((r["market_mid"] - r["y"]) ** 2 for r in rs) / len(rs),
            "disagreements": len(disagreements),
            "wins": wins,
        }
    return out


def topic_stats(journal, env: str = "shadow") -> dict[str, dict]:
    return group_stats(settled_forecasts(journal, env), lambda r: r["topic"])


def win_rate(stats: dict | None) -> float:
    """How often Claude beat the market when they disagreed, pulled toward 50% when there's little data."""
    if not stats:
        return 0.5
    return (stats["wins"] + PRIOR) / (stats["disagreements"] + 2 * PRIOR)


def topic_weights(stats: dict[str, dict]) -> dict[str, float]:
    return {t: win_rate(s) ** SHARPNESS for t, s in stats.items()}


NEUTRAL_WEIGHT = 0.5 ** SHARPNESS


def focus_label(topic: str, weights: dict[str, float]) -> str:
    ratio = weights.get(topic, NEUTRAL_WEIGHT) / NEUTRAL_WEIGHT
    if ratio >= 1.5:
        return "⬆ more"
    if ratio <= 0.67:
        return "⬇ less"
    return "normal"


def allocate(pool: list[dict], slots: int, weights: dict[str, float], explore_share: float,
             rng: random.Random) -> list[dict]:
    """Pick which markets get new research. Each pool item has a 'topic'; items are in
    priority order (highest volume first) within each topic. Adds 'picked_by' to each pick."""
    by_topic: dict = defaultdict(list)
    for item in pool:
        by_topic[item["topic"]].append(item)
    picks = []
    for _ in range(slots):
        topics = [t for t, items in by_topic.items() if items]
        if not topics:
            break
        if rng.random() < explore_share:
            topic, how = rng.choice(topics), "explore"
        else:
            topic = rng.choices(topics, weights=[weights.get(t, NEUTRAL_WEIGHT) for t in topics])[0]
            how = "focus"
        item = by_topic[topic].pop(0)
        picks.append({**item, "picked_by": how})
    return picks
