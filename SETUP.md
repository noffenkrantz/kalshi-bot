# Kalshi bot: setup guide

[← Back to the dashboard](README.md)

A trading simulator that runs itself on GitHub every 4 hours:

- **Watch:** pulls real open markets and live prices from Kalshi.
- **Think:** Claude reads each market's rules, searches the web, and gives a probability ("70% YES").
- **Simulate:** plain code compares that probability with the real price and subtracts Kalshi's fees. If the gap is big enough, it records a pretend trade. When the market settles, the pretend trade wins or loses based on what actually happened.

It never places a real order and never touches your money. The only real cost is Claude.

> This is a learning tool, not financial advice. Claude can be wrong, and a good simulated run can still be luck.

---

## Turn it on (phone, about 5 minutes)

1. In your phone's browser, go to **console.anthropic.com**. Add $10 of credit and **set a monthly spend limit** (for example $20) as a backstop. Then create an API key and copy it.
2. In this repo: **Settings → Secrets and variables → Actions → New repository secret**. Name it `ANTHROPIC_API_KEY`, paste the key, and tap **Add secret**. (On a phone browser, Settings may be under the **⋯** menu, or switch to "Desktop site.")
3. **Actions** tab → **kalshi-bot** → **Run workflow**.

About 5–10 minutes later, the repo's front page shows the dashboard. Tip: in Safari, Share → **Add to Home Screen** makes it open like an app.

## Controls from your phone

- **See results:** the repo's front page (the dashboard). `REPORT.md` has the detailed scorecard, and `data/last_run.log` shows what the last run did, including any errors.
- **Run now:** **Actions** → **kalshi-bot** → **Run workflow**.
- **Pause:** **Settings → Secrets and variables → Actions → Variables** → add `BOT_ENABLED` = `false`. Set it to `true` (or delete it) to restart.
- **Change settings:** open `config.toml`, tap the **pencil** icon, edit, then **Commit changes**. The next run uses them.

## How the simulation works

For every pretend trade:
- **Price:** it "buys" at the real asking price at that moment, and only as many contracts as were actually for sale at that price.
- **Fees:** it subtracts Kalshi's standard trading fee.
- **Result:** it holds the trade until the market settles, then counts it as a win or loss based on the real outcome.
- **Size:** every bet is $100 (`bet_size_dollars`) from a pretend $10,000 balance (`paper_bankroll`). If a full $100 can't be bought at the real price (not enough contracts for sale, or a limit would shrink it), it skips the bet. It never places smaller bets.

**How a real-money result could differ:** a real order lands seconds later, and the price can move in that time. Some markets charge different fees. And a person might sell early instead of holding to the end. At these small sizes, the simulated result should be close to what real money would have done.

**When you'll see results:** it only picks markets that settle within 12 hours to 10 days. So the first wins and losses come within days. Allow 2–3 weeks for about 100 settled forecasts, which is enough to tell skill from luck.

## How it learns

Claude's underlying model doesn't change. What improves is where the bot spends its research and the instructions Claude reads before researching. Both show up in the dashboard's **🧠 What Claude is learning** section.

**1. Learning where Claude is good.** Every settled forecast is scored against the market price at the time it was made. Results are grouped by topic (Kalshi's category, like Climate and Weather or Economics), by Claude's confidence, and by how far Claude was from the market. New research then follows the results:
- 80% goes to topics in proportion to how often Claude has beaten the market there. Each topic starts out assumed average, so a few results can't swing it much.
- 20% (`explore_share`) is spread at random, so a topic that had an unlucky streak still gets chances.

**2. Learning from mistakes, not luck.** After each simulated bet settles, Claude writes a post-mortem. It looks at the rules, what it believed, its sources and what actually happened, and can search once or twice to check. It then labels the bet **good call**, **bad luck**, **process mistake** or **unclear**. Only a process mistake (a misread rule, a stale source, missed information) becomes a lesson, and only if no existing lesson already covers it. A 90% call that loses 1 time in 10 is bad luck, not a lesson.

Lessons live in [`data/lessons.md`](data/lessons.md), tagged by topic. Claude reads the relevant ones before researching a market. You can delete a lesson by editing that file and removing its line.

**Checking the lessons actually help:** about 1 in 5 markets (`lessons_holdout_share`) is always researched *without* lessons. `REPORT.md` compares the two groups once enough have settled. If the lessons don't beat the control group, they're not helping.

Post-mortems count toward the daily research budget, at about $0.03–0.06 each. They run only with an API key; in subscription mode the topic learning still works, but post-mortems are skipped.

## Costs

- **Claude:** roughly $0.10–0.15 per forecast. It stops starting new research after about $2 a day (`daily_budget_usd`), so about $60 a month at most, roughly 15 forecasts a day. Forecasts are reused for 8 hours, so most runs cost little.
- **GitHub:** free. Private repos include 2,000 Actions minutes a month, and this uses well under that.

## Settings worth knowing (`config.toml`)

- `paper_bankroll` (default 10000): the pretend starting balance.
- `bet_size_dollars` (default 100): the size of every bet.
- `max_total_exposure`, `max_open_positions`: caps on how much is in open bets at once (default $3,000 across up to 30 bets).
- `min_edge` (default 0.08): how much better than the price, after fees, Claude's estimate must be (8 cents per $1 contract). Higher means fewer, more selective bets.
- `min_confidence`: "high" by default, so it bets only when Claude is highly confident. Set it to "medium" for more bets.
- `include_series`: focus on specific Kalshi series (the ticker prefix, like `KXHIGHNY`) instead of scanning everything. Narrowing to topics where research matters, such as economic data, weather or scheduled announcements, often works better.
- `exclude_categories`: Sports and Crypto are skipped by default, because those prices move fast and professional bots win there.
- `daily_budget_usd`, `max_new_analyses_per_run`: how much Claude research to do.
- `[learning]`: `explore_share` (default 20% random research), `lessons_holdout_share` (default 20% without lessons), `max_postmortems_per_run`.

## Reading the dashboard

- **Simulated account:** the pretend balance. Open trades are valued at today's prices.
- **Open and settled trades:** what was "bought," what it cost, what it's worth now, and wins and losses.
- **Is Claude beating the market?** This compares Claude's accuracy with the market price's (lower score is better). This is the key question: if Claude can't beat the price, there's no edge.
- `REPORT.md` adds calibration, which asks: when Claude says 70%, does it happen about 70% of the time?

## Safety

- **No real trading:** the automatic runs only simulate, and no Kalshi account or keys are involved.
- **Spending limits:** a daily cap on Claude spend, on top of the spend limit you set in the Anthropic console.
- **Prompt-injection guard:** Claude treats web pages as data and flags any page that tries to instruct it. Trade sizes and limits live in code, not in Claude's hands.

## If you ever consider real money

Only after **100+ settled forecasts** where Claude beats the market, with a positive simulated balance across many different markets, over several weeks. Even then, only use money you're fine losing. The code includes a locked real-trading mode, but the automatic runs never use it. Turning it on takes deliberate changes plus your own Kalshi API keys, so ask before going down that road.

## Optional: use your Claude subscription instead of an API key

This needs a computer once. Install Claude Code (`curl -fsSL https://claude.ai/install.sh | bash` on a Mac), run `claude setup-token`, and save the token it prints as a repo secret named `CLAUDE_CODE_OAUTH_TOKEN`. The bot switches to it automatically. It shares your plan's usage limits, and makes at most 12 forecasts a day by default.

## Troubleshooting

- **Nothing on the dashboard after a run:** open `data/last_run.log`. It shows each step's output and any errors.
- **"Research failed" lines:** usually a Claude API problem (no credit, wrong key, or a model name change). Check the `model` setting in `config.toml`.
- **"0 markets passed the filters":** the filters may be too strict for the moment. Try a higher `max_spread` or a lower `min_volume_24h`.
- **"Paused by a safety check":** read the reason. To clear it from a computer, run `python -m bot resume --mode shadow`, or ask Claude to clear it.

## How the code is organized

| File | Job |
|---|---|
| `bot/kalshi.py` | Reads Kalshi markets and prices |
| `bot/analyst.py` | Claude research with web search, then a structured estimate |
| `bot/research_queue.py` | Subscription mode: Claude Code does the research instead |
| `bot/strategy.py` | Fees, edge, sizing and limits (pure math, no AI) |
| `bot/learning.py` | Topic scorecard and research-budget allocation |
| `bot/postmortem.py`, `bot/lessons.py` | Post-mortems and the lessons file |
| `bot/runner.py` | One full run: review settled bets → scan → research → decide → record simulated trades |
| `bot/journal.py` | Logs everything to `data/*.jsonl` |
| `bot/report.py`, `bot/dashboard.py` | The scorecard (`REPORT.md`) and dashboard (`README.md`) |
| `.github/workflows/bot.yml` | The every-4-hours schedule |
| `tests/` | Offline tests: `python -m pytest -q` |

(The code also has practice-exchange and real-money modes for running on a computer. The automatic runs don't use them.)
