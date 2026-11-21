# Kalshi + Claude practice bot: setup guide

[← Back to the dashboard](README.md)

A small program that uses Claude to research Kalshi markets and place **practice** trades on its own.

- **Watch**: pulls open markets and live prices from Kalshi.
- **Think**: Claude reads each market's rules, searches the web, and gives a probability ("70% YES").
- **Act**: plain code compares that probability with the price, subtracts Kalshi's fees, and buys only when the gap is big enough. Hard limits cap every trade.

Claude never decides how much to spend. The rules in `config.toml` do.

> This is a learning and testing tool, not financial advice. Claude can be wrong, and it's slower than the professional bots on Kalshi. Everything here runs on practice money or paper trades until you choose otherwise.

---

## Quick start: everything from your phone

The bot lives in this repo and runs itself on GitHub every 4 hours. There's nothing to install. You just add keys in **Settings → Secrets and variables → Actions**. (On a phone browser, Settings may be under the **⋯** menu, or switch to "Desktop site.")

**1. Turn on the brain (about 5 minutes)**
- In your phone's browser, go to **console.anthropic.com**. Add $10 of credit and **set a monthly spend limit** (for example $20) as your backstop.
- Create an API key and copy it.
- In this repo: **New repository secret** → name `ANTHROPIC_API_KEY` → paste the key → **Add secret**.
- **Actions** tab → **kalshi-bot** → **Run workflow**.

About 5–10 minutes later, open the repo's front page. The **dashboard** there shows Claude's first forecasts against real Kalshi prices. Each forecast costs roughly $0.10–0.15, and it stops starting new research after about $1 a day.

**2. Turn on practice trading (whenever you're ready)**
- Sign up at **demo.kalshi.co**. This is Kalshi's practice site with fake money, separate from your real account.
- In its account settings, create an **API key**. You'll get a **Key ID** and a **private key**, which is shown once, usually as a file download. Save both right away.
- Add two secrets: `KALSHI_DEMO_API_KEY_ID` (the Key ID) and `KALSHI_DEMO_PRIVATE_KEY` (the whole private key text, including the `-----BEGIN` and `-----END` lines).
  - *On an iPhone:* the key file lands in the **Files** app → Downloads. Tap it to view it. If it won't open as text, long-press → **Rename**, add `.txt` to the end, and tap it again. Then select all and copy.
- The next run starts placing practice trades.

**Controls from your phone**
- **See results:** open the repo. Its front page is the **dashboard**: your practice account, open and settled trades, and whether Claude is beating the market. `REPORT.md` has the detailed scorecard, and `data/last_run.log` shows what the last run did, including any errors.
- **See the practice account on Kalshi itself:** sign in at demo.kalshi.co. Its portfolio page shows the same fake-money positions the bot placed.
- **Run now:** **Actions** → **kalshi-bot** → **Run workflow**.
- **Pause everything:** **Settings → Secrets and variables → Actions → Variables** → add `BOT_ENABLED` = `false`. Set it to `true` (or delete it) to restart.
- **Pause only practice trading:** add the variable `DEMO_TRADING` = `false`.
- **Change settings:** open `config.toml` in the repo, tap the **pencil** icon, edit, and **Commit changes**. The next run uses the new values.

*Want to use your Claude subscription instead of an API key later?* That needs a computer once: install Claude Code, run `claude setup-token`, and save the token as a secret named `CLAUDE_CODE_OAUTH_TOKEN`. The bot switches to it automatically, and you can delete the API key secret.

The rest of this guide covers running it on your own computer, the settings, and how to read the report.

---

## The plan: 3 phases

| Phase | What happens | Money at risk | Move on when |
|---|---|---|---|
| **1. Shadow** | Claude forecasts **real** markets at real prices. The bot records "paper trades" but places nothing. | None (only Claude API costs) | `check` passes and runs work without errors |
| **2. Demo trading** | The bot places real orders on Kalshi's **practice exchange**, using fake money. | None | A week of clean runs |
| **3. Automatic** | GitHub runs shadow and demo every 4 hours, even with your laptop closed. | None | You decide, using the report |

Shadow mode is the honest test of whether Claude has an edge, because it uses real prices. Demo mode tests the trading machinery, but the practice exchange is quiet and its prices aren't realistic.

---

## What you need

- A computer with **Python 3.11 or newer** (`python3 --version` to check)
- A **Claude API** account with a few dollars of credit (Phase 1)
- A free **Kalshi demo** account (Phase 2)
- A free **GitHub** account (Phase 3)

**Costs:** Each new forecast costs roughly $0.10–0.15 in Claude API fees (research, a few web searches, then the final estimate). The default cap is **$1 per mode per day**, so at most about $2/day once both shadow and demo run. Lower `daily_budget_usd` in `config.toml` to spend less. Forecasts are reused for 8 hours, so most runs cost little.

---

## Step 1: Install (10 minutes)

Unzip the folder, open a terminal in it, then:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Run `source .venv/bin/activate` again whenever you open a new terminal.

## Step 2: Claude API key

1. Sign in at **console.anthropic.com** and add a little credit ($10 is plenty to start).
2. **Set a monthly spend limit** in the console's limits/billing settings (for example $20). This is your backstop if anything misbehaves.
3. Create an API key and paste it into `.env` after `ANTHROPIC_API_KEY=`.

Then check it:

```bash
python -m bot check
```

You should see `[OK]` for Claude and for Kalshi market data. Demo will show `[--]`, which is fine for now.

## Step 3: Phase 1, shadow mode

```bash
python -m bot run --mode shadow
```

Each run:
1. Scans Kalshi's open markets and drops ones that close too soon, are near-certain, have wide spreads or little trading, or are in Sports or Crypto.
2. Researches up to 4 new markets with Claude (about a minute each).
3. Prints each forecast next to the market price, plus any **paper trade**: what it would buy, at the real ask price, after fees.

Example output:
```
Forecast KXCPI-26NOV-T0.3: Claude 71% YES (medium) vs market 55% - CPI in November...
Paper trade: would buy 42 YES on KXCPI-26NOV-T0.3 at $0.57 (edge +0.12/contract, ~$24.67)
```

Run it a few times a day. You can skip ahead to Phase 3 and let GitHub do this for you. After markets start resolving:

```bash
python -m bot report
```

Everything is logged in `data/` as readable text files (`estimates.jsonl`, `decisions.jsonl`, ...).

## Step 4: Kalshi practice (demo) account and API key

1. Sign up at **demo.kalshi.co**. This is Kalshi's practice exchange with fake money, separate from the real site.
2. In your demo account settings, find **API Keys** and create one. You'll get a **Key ID** and a **private key file**. Download the file right away, because it's only shown once.
3. Put the private key file in this project's `secrets/` folder and name it `kalshi-demo.key`.
4. Paste the Key ID into `.env` after `KALSHI_DEMO_API_KEY_ID=`.

Demo keys only work on the demo exchange, and real-account keys only work on the real one. That separation is a safety feature.

`python -m bot check` should now show your practice balance.

## Step 5: Phase 2, demo trading

```bash
python -m bot run --mode demo
```

The demo run uses the same research and rules, but places real orders on the practice exchange. Orders are **immediate-or-cancel** at the current best price: they fill right away or not at all, so no stale orders are left sitting around.

**After the first trade,** open demo.kalshi.co and check that the position matches the log (for example "BOUGHT 12 NO on X"). The bot also checks this itself: after every order it asks Kalshi whether it was recorded as YES or NO, and halts if that doesn't match what it meant.

If the bot says "0 markets passed the filters," the practice exchange may just be quiet. Try again later, or widen `max_spread` in `config.toml`.

## Step 6: Phase 3, fully automatic (GitHub Actions)

GitHub will run the bot every 4 hours on its own computers and save the journal back to your repository after each run. (If your repo already came set up on GitHub, skip to step 3.) Free GitHub accounts include 2,000 minutes a month for private repos, and this uses roughly 1,000–1,500.

1. **Create a private repository** on GitHub. It must be private, because the journal records your trades.
2. **Upload the project** with git, from the project folder:
   ```bash
   git init && git add . && git commit -m "kalshi bot"
   git branch -M main
   git remote add origin https://github.com/YOUR-NAME/YOUR-REPO.git
   git push -u origin main
   ```
   `.gitignore` keeps `.env` and `secrets/` from being uploaded. If you upload through the website instead, make sure the hidden `.github` folder is included.
3. **Add secrets**: repo **Settings → Secrets and variables → Actions → Secrets → New repository secret**:
   - `ANTHROPIC_API_KEY`: your Claude key
   - `KALSHI_DEMO_API_KEY_ID`: your demo Key ID
   - `KALSHI_DEMO_PRIVATE_KEY`: open the key file in a text editor and paste **the whole thing**, including the `-----BEGIN` and `-----END` lines
   You need either `CLAUDE_CODE_OAUTH_TOKEN` (your Claude subscription, see Quick start) or `ANTHROPIC_API_KEY`. Without the two Kalshi secrets it runs shadow mode only.
4. **Test it**: **Actions** tab → *kalshi-bot* → **Run workflow**. Open the run to see a readable summary of what it did.

From now on it runs every 4 hours. Check the dashboard and runs, and flip the switch, from your phone.

- **Emergency stop:** add a variable `BOT_ENABLED` = `false` (Variables tab), or disable the workflow in the Actions tab.
- **Shadow only:** add a variable `DEMO_TRADING` = `false`.
- Once GitHub is running it, run `git pull` before running anything locally, so the journals don't conflict.

---

## Safety features

- **Practice only by default.** Real-money mode is locked behind two switches (see the last section).
- **Hard limits** in `config.toml`: dollars per trade, total exposure, open positions, spending per day, trades per run.
- **Drawdown halt:** if account value falls 30% below its peak, the bot stops until you run `python -m bot resume --mode demo`.
- **Direction self-check:** halts if Kalshi records a trade as the opposite side from what the bot intended.
- **Claude budget cap** per day, on top of the spend limit you set in the Anthropic console.
- **Kill switches:** a file named `STOP` in the project folder, the `BOT_DISABLED=1` environment variable, or `BOT_ENABLED=false` on GitHub.
- **Prompt-injection guard:** Claude is told to treat web pages as data and to report any page that tries to instruct it. And because sizing and limits live in code, a manipulated forecast can't exceed your caps.
- **No double orders:** order requests are never automatically retried.

## Settings worth knowing (`config.toml`)

- `min_edge` (default 0.05): how much better than the price, after fees, Claude's estimate must be. Higher means fewer, more selective trades.
- `min_confidence`: "medium" by default. Set it to "high" to be pickier.
- `include_series`: focus on specific Kalshi series (the ticker prefix, like `KXHIGHNY`) instead of scanning everything. Narrowing to topics where research matters, such as economic data, weather or scheduled announcements, often works better than scanning everything.
- `exclude_categories`: Sports and Crypto are skipped by default, because those prices move fast and bots win there.
- `show_market_price_to_claude`: off by default, so Claude forms its own view and the scorecard measures real independent skill.

## Reading the report

`python -m bot report` shows, for each mode:

- **Accuracy (Brier score):** the average squared gap between forecast and outcome. Lower is better, and always guessing 50% scores 0.25. **The key line is Claude vs the market price.** If Claude isn't beating the price, there's no edge to trade on.
- **When Claude disagreed with the market:** how often Claude was the one closer to the truth. These are the cases that become trades.
- **Calibration:** when Claude says 70%, does it happen about 70% of the time?
- **Paper trades / filled orders:** wins and approximate profit and loss on settled markets.

The report won't give a verdict until **100 shadow forecasts** have resolved. Fewer than that is mostly luck.

## Before you ever use real money

Only consider it if all of these are true:

- [ ] 100+ resolved shadow forecasts, and Claude's Brier score beats the market's
- [ ] Positive paper P&L across many different markets, not one lucky streak
- [ ] Weeks of automatic runs with no halts or errors you can't explain
- [ ] You've read Kalshi's developer agreement and fee schedule
- [ ] You're fine losing every dollar you put in

Real-money mode then needs **both** `enabled = true` in the `[live]` section of `config.toml` **and** the environment variable `ALLOW_REAL_MONEY=yes`, plus separate production keys (`KALSHI_PROD_API_KEY_ID`, `KALSHI_PROD_PRIVATE_KEY_PATH`). It uses the much smaller `[live]` limits (default $5 per trade, $50 total). The GitHub workflow never runs live mode as written.

## Troubleshooting

- **Kalshi 401 (unauthorized):** the key doesn't match the exchange (demo key on the real site or vice versa), the key file is wrong, or your computer's clock is off. Kalshi rejects requests more than 30 seconds out.
- **Kalshi 410 (gone):** Kalshi retired an endpoint. The bot halts. The API changes regularly, so check docs.kalshi.com/changelog.
- **Claude 400 errors:** usually a model name or pricing change. Check the `model` setting in `config.toml`.
- **"halted" messages:** read the reason, fix what it points to, then run `python -m bot resume --mode demo`.
- **Run the self-tests** (no network or keys needed): `pip install pytest && python -m pytest -q`

## How the code is organized

| File | Job |
|---|---|
| `bot/kalshi.py` | Talks to Kalshi: signing, markets, balance, positions, orders |
| `bot/analyst.py` | Claude research (with web search), then the structured estimate (API-key mode) |
| `bot/research_queue.py` | Subscription mode: queues markets for Claude Code and reads back its forecasts |
| `bot/strategy.py` | Fees, edge, sizing and limits (pure math, no AI) |
| `bot/runner.py` | One full run: safety checks → account → scan → research → decide → trade |
| `bot/journal.py` | Logs everything to `data/*.jsonl` |
| `bot/report.py` | The scorecard |
| `.github/workflows/bot.yml` | The every-4-hours schedule for Phase 3 |
| `README.md` | The dashboard (repo front page), rebuilt after each run |
| `REPORT.md` | Detailed scorecard, updated after each run |
| `bot/dashboard.py` | Builds the dashboard |
