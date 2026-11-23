# Kalshi bot

**Updated Sun Nov 22, 10:12 PM EST** · runs every 4 hours · [▶ Run now](https://github.com/noffenkrantz/kalshi-bot/actions/workflows/bot.yml) · [Results site](https://noffenkrantz.github.io/kalshi-bot/) · [Full report](REPORT.md) · [Where prices lag](LAGS.md) · [Last run log](data/last_run.log) · [Setup & settings](SETUP.md)

## 💵 Simulated account

*Real Kalshi markets at real prices, with Kalshi's fees, settled on what actually happened. The money is pretend: nothing is ever bought.*

### $10,000.00
+$0.00 since the start ($10,000.00 pretend bankroll). Real balance: settled bets only.

Projected: **$9,928.19** (−$71.81) if the open bets whose prices have moved ended at today's prices.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="data/balance-dark.svg">
  <img alt="Chart of the real balance over time, now $10,000.00, with the projection dashed" src="data/balance-light.svg" width="100%">
</picture>

1 open trade ($99.97 in) · none settled yet · projected = what an open trade would be worth if it ended at today's price, shown once its price has moved

**Open trades**

| Market | Bet | Cost | Now | Projected |
|---|---|---|---|---|
| US gas prices tomorrow — Above 3.6350 | 131 NO @ 75¢ | $99.97 | 21¢ | −$71.81 |

## 🎯 Is Claude beating the market?

**Claude is ahead**: accuracy score 0.087 for Claude vs 0.232 for the market price (lower is better) on 3 resolved forecasts. Too early to trust: 3/100 resolved.

## 🧠 What Claude is learning

**Where Claude is good** (settled forecasts where Claude and the market disagreed by 5+ points)

| Topic | Claude beat the market | Research focus |
|---|---|---|
| Politics | 1 of 2 | normal |
| Climate and Weather | 1 of 1 | ⬆ more |

*20% of research is always spread at random, so every topic keeps getting chances.*

**Lessons learned (0)** · [see all or edit](data/lessons.md)
- None yet. Only process mistakes become lessons, never bad luck.

## 🔮 Latest forecasts

| Market | Claude | Market | Sure? |
|---|---|---|---|
| Highest temperature in Los Angeles on Nov… | 10% | 6% | medium-low |
| Trump's RCP approval average on Nov 23, 2… | 40% | 40% | medium-low |
| Connecticut gas price tomorrow — Small de… | 42% | 72% | medium |
| Vermont gas price tomorrow — Large decrea… | 45% | 42% | medium-low |
| US gas prices tomorrow — Above 3.6350 | 12% | 26% | medium-high |
| Highest temperature in Houston on Nov 23,… | 20% | 78% | medium |
| Where will it rain on Nov 23, 2026? — Alb… | 12% | 56% | medium |
| Diesel prices tomorrow — Above $5.815 | 42% | 94% | medium-low |
| Trump Truth Social posts on Nov 22, 2026?… | 5% | 20% | medium-high |
| What will the biggest earthquake be on No… | 11% | 17% | medium |

---
*Simulated trades only, no real money. Not financial advice.*
