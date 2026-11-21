"""Command line: python -m bot check | run --mode shadow|demo|live | report | resume --mode ..."""
from __future__ import annotations

import argparse
import os
import sys

from .claude import ClaudeClient, ClaudeError
from .config import DATA_DIR, ROOT, load_config, resolve_path
from .journal import Journal
from .kalshi import KalshiClient, KalshiError, load_private_key
from .report import build_report
from .runner import Bot, run_once, write_step_summary
from .util import utcnow


def kalshi_client(env: str, prefix: str | None) -> KalshiClient:
    """prefix is DEMO or PROD; None means public market data only."""
    if prefix:
        key_id = os.environ.get(f"KALSHI_{prefix}_API_KEY_ID")
        pem = os.environ.get(f"KALSHI_{prefix}_PRIVATE_KEY")
        path = resolve_path(os.environ.get(f"KALSHI_{prefix}_PRIVATE_KEY_PATH"))
        if key_id and (pem or path):
            return KalshiClient(env, key_id=key_id, private_key=load_private_key(pem, path))
    return KalshiClient(env)


def claude_client(cfg: dict) -> ClaudeClient | None:
    """API-key mode if ANTHROPIC_API_KEY is set; otherwise None (subscription mode,
    where Claude Code has already written the forecasts via prepare/ingest)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("No ANTHROPIC_API_KEY: using forecasts made by Claude Code (subscription mode).")
        return None
    return ClaudeClient(key, cfg["claude"]["prices"])


def cmd_prepare(cfg: dict) -> int:
    from .research_queue import prepare
    clients = {"shadow": KalshiClient("prod")}
    demo = kalshi_client("demo", "DEMO")
    if demo.authenticated and os.environ.get("DEMO_TRADING", "").lower() != "false":
        clients["demo"] = demo
    queue = prepare(cfg, clients, Journal(DATA_DIR), utcnow(), ROOT / "work")
    print(f"{len(queue)} market(s) queued for Claude Code to research:")
    for item in queue:
        print(f"  [{item['env']}] {item['ticker']}: {item['question'][:90]}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"count={len(queue)}\n")
    return 0


def cmd_ingest() -> int:
    from .research_queue import ingest
    added, problems = ingest(Journal(DATA_DIR), ROOT / "work", utcnow())
    print(f"Recorded {added} forecast(s) from Claude Code.")
    for p in problems:
        print(f"  ! {p}")
    write_step_summary(f"### Claude Code research\n\n- {added} forecast(s) recorded\n"
                       + "".join(f"- {p}\n" for p in problems))
    return 0


def cmd_check(cfg: dict) -> int:
    ok = True
    print("Checking setup...\n")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("[X] Claude: ANTHROPIC_API_KEY not set"); ok = False
    else:
        try:
            ClaudeClient(key, cfg["claude"]["prices"]).create({
                "model": cfg["claude"]["model"], "max_tokens": 5,
                "messages": [{"role": "user", "content": "Reply with OK"}]})
            print(f"[OK] Claude API works (model {cfg['claude']['model']})")
        except ClaudeError as e:
            print(f"[X] Claude API: {e}"); ok = False
    try:
        st = KalshiClient("prod").exchange_status()
        print(f"[OK] Kalshi real market data reachable (trading active: {st.get('trading_active')})")
    except KalshiError as e:
        print(f"[X] Kalshi market data: {e}"); ok = False
    try:
        demo = kalshi_client("demo", "DEMO")
        if demo.authenticated:
            bal = demo.get_balance()
            cash = bal.get("balance_dollars") or (bal.get("balance", 0) / 100)
            print(f"[OK] Kalshi DEMO account works, practice balance ${float(cash):,.2f}")
        else:
            print("[--] Kalshi DEMO key not set up yet (fine for Phase 1 shadow mode)")
    except (KalshiError, ValueError, OSError) as e:
        print(f"[X] Kalshi DEMO account: {e}"); ok = False
    print("\nAll good." if ok else "\nFix the [X] items above (see SETUP.md > Troubleshooting).")
    return 0 if ok else 1


def cmd_run(cfg: dict, mode: str) -> int:
    journal = Journal(DATA_DIR)
    if mode == "shadow":
        data, trade = KalshiClient("prod"), None
    elif mode == "demo":
        data = trade = kalshi_client("demo", "DEMO")
        if not trade.authenticated:
            sys.exit("Demo mode needs KALSHI_DEMO_API_KEY_ID and a demo private key (see SETUP.md step 4).")
    else:
        data = trade = kalshi_client("prod", "PROD")
        if not trade.authenticated:
            sys.exit("Live mode needs KALSHI_PROD_API_KEY_ID and a production private key.")
    bot = Bot(mode=mode, cfg=cfg, data=data, trade=trade, claude=claude_client(cfg),
              journal=journal, now=utcnow())
    try:
        summary = run_once(bot)
    except KalshiError as e:
        bot.summary.add(f"Stopped on a Kalshi error: {e}")
        summary = bot.summary
    write_step_summary(summary.markdown())
    return 0


def cmd_report(cfg: dict) -> int:
    journal = Journal(DATA_DIR)
    clients = {"shadow": KalshiClient("prod"), "demo": kalshi_client("demo", "DEMO"),
               "live": KalshiClient("prod")}
    text = build_report(journal, clients, utcnow(), cfg["strategy"]["min_edge"])
    print(text)
    write_step_summary(text)
    recent = [r for r in journal.rows["estimates"]][-15:]
    lines = [text, "", "## Latest forecasts", "",
             "| When (UTC) | Market | Claude | Market price | Confidence |", "|---|---|---|---|---|"]
    for r in reversed(recent):
        mid = r.get("market_mid")
        lines.append(f"| {r.get('ts', '')[:16]} | {str(r.get('question', r.get('ticker')))[:70]} | "
                     f"{r.get('prob_yes', 0):.0%} | {'' if mid is None else f'{mid:.0%}'} | {r.get('confidence')} |")
    (ROOT / "REPORT.md").write_text("\n".join(lines) + "\n")
    from .dashboard import build_dashboard
    (ROOT / "README.md").write_text(build_dashboard(journal, clients, utcnow(), cfg, record=True))
    return 0


def cmd_resume(mode: str) -> int:
    journal = Journal(DATA_DIR)
    journal.set_state(f"halted:{mode}", None)
    journal.set_state(f"peak_equity:{mode}", None)
    print(f"{mode} mode resumed (halt cleared, peak account value reset).")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bot", description="Kalshi + Claude practice bot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="test your keys and connections")
    run = sub.add_parser("run", help="do one pass: scan, research, decide, (maybe) trade")
    run.add_argument("--mode", choices=["shadow", "demo", "live"], default="shadow")
    sub.add_parser("report", help="show how Claude's forecasts and trades are doing")
    sub.add_parser("prepare", help="subscription mode: queue markets for Claude Code to research")
    sub.add_parser("ingest", help="subscription mode: record Claude Code's forecasts")
    res = sub.add_parser("resume", help="clear a safety halt")
    res.add_argument("--mode", choices=["shadow", "demo", "live"], required=True)
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.cmd == "check":
        return cmd_check(cfg)
    if args.cmd == "run":
        return cmd_run(cfg, args.mode)
    if args.cmd == "report":
        return cmd_report(cfg)
    if args.cmd == "prepare":
        return cmd_prepare(cfg)
    if args.cmd == "ingest":
        return cmd_ingest()
    return cmd_resume(args.mode)


if __name__ == "__main__":
    sys.exit(main())
