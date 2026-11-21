"""Self-improvement, part 2: learn from mistakes, not from luck.

After each simulated bet settles, Claude reviews it: the question, the rules, what it
believed and why, its sources, and what actually happened. It must decide whether the
PROCESS was wrong (a misread rule, a stale source, missed information) or whether a
reasonable forecast simply lost. Only process mistakes become lessons.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .analyst import CostMeter, _collect, _parse_json
from .claude import ClaudeClient, ClaudeError
from .kalshi import KalshiClient, KalshiError
from .learning import topic_for
from .lessons import add_or_reinforce, load, numbered

SYSTEM = """You review one settled prediction-market bet to improve the research process.

Judge the PROCESS, not the outcome. Good forecasts lose sometimes: a 90% call should lose about 1 time in 10, and a 70% call about 3 times in 10. A loss is not, by itself, evidence of a mistake, and a win doesn't prove the process was right.

Use "process_mistake" only when you can point to a specific, checkable error, for example:
- the rules were misread (wrong threshold, resolution source, date, time zone, or what counts as YES)
- a stale source was used when fresher information was available at the time of the forecast
- relevant information that was available at the time was missed or ignored
- an arithmetic or timing error
Otherwise use "bad_luck" (the forecast was reasonable and the less likely outcome happened), "good_call" (the bet won and the reasoning held up), or "unclear" (you can't tell).

A lesson must be a general, reusable instruction for future research, such as: "For rain markets, check whether the rules count a trace as zero before relying on forecast rain chances." Never write a lesson about this market's outcome, and never one like "be less confident about X" based on a single result. Only write a lesson for a process_mistake. If an existing lesson already covers it, leave lesson empty and give that lesson's number in reinforces.

You may search the web once or twice to check what actually happened or what information existed at the time.

End your reply with ONLY a JSON object with these keys:
{"verdict": "process_mistake" | "bad_luck" | "good_call" | "unclear",
 "what_happened": "one or two sentences",
 "mistake": "the specific error, or empty string",
 "lesson": "general instruction, or empty string",
 "applies_to": "this topic" | "all topics",
 "reinforces": 0}"""

VERDICTS = ("process_mistake", "bad_luck", "good_call", "unclear")


def pending_reviews(journal, env: str = "shadow") -> list[dict]:
    reviewed = {p["ticker"] for p in journal.rows["postmortems"] if p.get("env") == env}
    out, seen = [], set()
    for d in journal.rows["decisions"]:
        if d.get("env") != env or not d.get("action", "").startswith("paper_buy"):
            continue
        ticker = d["ticker"]
        if ticker in reviewed or ticker in seen:
            continue
        result = journal.outcome(env, ticker)
        if result:
            out.append({**d, "result": result})
            seen.add(ticker)
    return out


def _brief(bet: dict, est: dict, market: dict, lessons: list[dict]) -> str:
    won = bet["result"] == bet["outcome"]
    pnl = (bet["count"] if won else 0) - (bet.get("est_cost") or 0)
    lines = [
        f"Question: {est.get('question') or bet['ticker']}",
        f"Ticker: {bet['ticker']}   Trading closed: {market.get('close_time') or est.get('close_time')}",
        "Rules:\n" + (market.get("rules_primary") or est.get("summary") or "(not available)"),
    ]
    if market.get("rules_secondary"):
        lines.append("More rules:\n" + market["rules_secondary"])
    if market.get("expiration_value") not in (None, ""):
        lines.append(f"Official settlement value: {market['expiration_value']}")
    lines += [
        f"RESULT: the market settled {bet['result'].upper()}.",
        "",
        f"Forecast made {est.get('ts')}: Claude said {est.get('prob_yes', 0):.0%} YES "
        f"(confidence {est.get('confidence')}); the market price was {est.get('market_mid') or 0:.0%}.",
        f"Bet: bought {bet['count']} {bet['outcome'].upper()} at ${bet.get('outcome_price', 0):.2f} -> "
        f"{'WON' if won else 'LOST'} (about ${pnl:+.2f}).",
        f"What Claude thought had to happen for YES: {est.get('summary', '')}",
        "Key evidence it used:\n" + "\n".join(f"- {x}" for x in est.get("evidence", [])),
        "Red flags it noted:\n" + ("\n".join(f"- {x}" for x in est.get("red_flags", [])) or "- none"),
        "Sources:\n" + ("\n".join(f"- {x}" for x in est.get("sources", [])) or "- none recorded"),
    ]
    if est.get("notes"):
        lines.append("Research notes (excerpt):\n" + est["notes"][:3000])
    lines += ["", "Existing lessons:\n" + numbered(lessons)]
    return "\n".join(lines)


def review_bet(claude: ClaudeClient, cfg: dict, bet: dict, est: dict, market: dict,
               lessons: list[dict], meter: CostMeter) -> dict:
    model = cfg["claude"]["model"]
    tools = [{"type": "web_search_20250305", "name": "web_search",
              "max_uses": int(cfg.get("learning", {}).get("postmortem_searches", 2))}]
    messages = [{"role": "user", "content": _brief(bet, est, market, lessons)}]
    texts, _sources = [], []
    for _ in range(4):
        resp = claude.create({"model": model, "max_tokens": 2000, "system": SYSTEM,
                              "messages": messages, "tools": tools})
        meter.add(claude.cost_usd(resp.get("usage"), model))
        _collect(resp.get("content", []), texts, _sources)
        if resp.get("stop_reason") == "pause_turn":
            messages = messages + [{"role": "assistant", "content": resp.get("content", [])}]
            continue
        break
    text = "\n".join(texts)
    start, end = text.rfind("{"), text.rfind("}")
    try:
        data = _parse_json(text[start:end + 1] if start != -1 and end > start else text)
    except ValueError as e:
        raise ClaudeError(f"post-mortem reply wasn't readable JSON: {e}") from e
    verdict = str(data.get("verdict", "unclear")).lower().strip()
    if verdict not in VERDICTS:
        verdict = "unclear"
    try:
        reinforces = int(data.get("reinforces") or 0)
    except (TypeError, ValueError):
        reinforces = 0
    return {"verdict": verdict,
            "what_happened": str(data.get("what_happened", ""))[:400],
            "mistake": str(data.get("mistake", ""))[:300] if verdict == "process_mistake" else "",
            "lesson": str(data.get("lesson", "")).strip() if verdict == "process_mistake" else "",
            "applies_to": "all topics" if "all" in str(data.get("applies_to", "")).lower() else "this topic",
            "reinforces": reinforces if verdict == "process_mistake" else 0}


def run_postmortems(journal, claude: ClaudeClient, data_client: KalshiClient, cfg: dict,
                    lessons_path: Path, now: datetime, budget_left: float, say) -> float:
    """Review settled bets (a few per run). Returns what it spent."""
    lcfg = cfg.get("learning", {})
    spent = 0.0
    for bet in pending_reviews(journal)[: int(lcfg.get("max_postmortems_per_run", 3))]:
        if budget_left - spent <= 0:
            break
        ticker = bet["ticker"]
        est = journal.latest_estimate(ticker) or {}
        try:
            market = data_client.get_market(ticker)
        except KalshiError:
            market = {}
        topic = topic_for(est or bet, journal)
        meter = CostMeter()
        try:
            review = review_bet(claude, cfg, bet, est, market, load(lessons_path), meter)
        except ClaudeError as e:
            say(f"Post-mortem failed for {ticker}: {e}")
            continue
        finally:
            journal.append("claude_costs", {"ts": now.isoformat(timespec="seconds"), "env": "shadow",
                                            "ticker": ticker, "kind": "postmortem", "usd": round(meter.total, 4)})
            spent += meter.total
        action = ""
        if review["verdict"] == "process_mistake" and (review["lesson"] or review["reinforces"]):
            lesson_topic = "All" if review["applies_to"] == "all topics" else topic
            action = add_or_reinforce(lessons_path, lesson_topic, review["lesson"], review["reinforces"],
                                      now.strftime("%Y-%m-%d"), int(lcfg.get("max_lessons", 30)))
        journal.append("postmortems", {"ts": now.isoformat(timespec="seconds"), "env": "shadow",
                                       "ticker": ticker, "topic": topic, "won": bet["result"] == bet["outcome"],
                                       **review, "lesson_action": action, "cost_usd": round(meter.total, 4)})
        label = {"process_mistake": "process mistake", "bad_luck": "bad luck (no lesson)",
                 "good_call": "good call", "unclear": "unclear"}[review["verdict"]]
        say(f"Post-mortem {ticker}: {label}" + (f" -> lesson {action}" if action else ""))
    return spent
