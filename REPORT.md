# Kalshi bot report - 2026-11-23T13:40:04+00:00

## SHADOW
Forecasts: 27 made, 9 resolved
Accuracy (Brier, lower is better): Claude 0.1928 vs market price 0.1898 -> Claude is WORSE than the market
When Claude disagreed with the market by 8%+: Claude was closer 2 of 6 times
Calibration (when Claude says X%, how often is it YES?):
  0%-20%:   4 forecasts, avg said 8%, actually YES 25%
  20%-40%:   1 forecasts, avg said 30%, actually YES 0%
  40%-60%:   4 forecasts, avg said 45%, actually YES 25%
Paper trades (at real prices, assuming fills at the ask): 1 total, 1 settled, 0 won, P&L on settled ~$-99.97
Real balance (settled bets only): $10,000.00; projected with moved open bets at today's prices: $9,928.19

## Where Claude does well (simulation, settled forecasts)

**By topic**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| Climate and Weather | 5 | 0.142 | 0.089 | 1 of 3 |
| Politics | 3 | 0.084 | 0.236 | 2 of 3 |
| Economics | 1 | 0.774 | 0.555 | 0 of 1 |

**By Claude's confidence**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| medium | 4 | 0.094 | 0.048 | 1 of 3 |
| low | 3 | 0.194 | 0.307 | 1 of 2 |
| medium-high | 2 | 0.388 | 0.298 | 1 of 2 |

**By distance from the market price**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| 5–15 pts from market | 4 | 0.287 | 0.186 | 1 of 4 |
| 15+ pts from market | 3 | 0.121 | 0.232 | 2 of 3 |
| within 5 pts of market | 2 | 0.112 | 0.134 | – |

(Scores are Brier scores: lower is better.)

**Do the lessons help?** (about 20% of markets are researched without lessons, as a control)
With lessons: 0.142 on 5 forecasts · without: 0.257 on 4. Lessons look helpful so far. Small samples are noisy.

Claude API spend: ~$4.14 in the last 7 days, ~$4.14 all time

## Verdict
Not enough data yet: 9/100 shadow forecasts have resolved. Keep collecting before drawing conclusions.

## Latest forecasts

| When (UTC) | Market | Claude | Market price | Confidence |
|---|---|---|---|---|
| 2026-11-23T13:37 | Where will it rain on Nov 24, 2026? — Tampa | 20% | 40% | medium |
| 2026-11-23T13:37 | Michigan gas price tomorrow — Large decrease | 50% | 15% | medium-low |
| 2026-11-23T13:37 | Diesel prices tomorrow — Above $5.805 | 6% | 10% | medium |
| 2026-11-23T13:37 | US gas prices tomorrow — Above 3.6150 | 52% | 15% | medium-low |
| 2026-11-22T21:59 | Highest temperature in Los Angeles on Nov 23, 2026? — 71° to 72° | 10% | 6% | medium-low |
| 2026-11-22T21:59 | Trump's RCP approval average on Nov 23, 2026? — 37.9% | 40% | 40% | medium-low |
| 2026-11-22T21:59 | Connecticut gas price tomorrow — Small decrease | 42% | 72% | medium |
| 2026-11-22T21:59 | Vermont gas price tomorrow — Large decrease | 45% | 42% | medium-low |
| 2026-11-22T15:54 | US gas prices tomorrow — Above 3.6350 | 12% | 26% | medium-high |
| 2026-11-22T15:54 | Highest temperature in Houston on Nov 23, 2026? — 67° or below | 20% | 78% | medium |
| 2026-11-22T15:54 | Where will it rain on Nov 23, 2026? — Albuquerque | 12% | 56% | medium |
| 2026-11-22T15:54 | Diesel prices tomorrow — Above $5.815 | 42% | 94% | medium-low |
| 2026-11-22T06:54 | Trump Truth Social posts on Nov 22, 2026? — <5 | 5% | 20% | medium-high |
| 2026-11-22T04:26 | What will the biggest earthquake be on Nov 22, 2026? — Magnitude of at | 11% | 17% | medium |
| 2026-11-21T21:58 | Highest temperature in Los Angeles on Nov 22, 2026? — 67° to 68° | 30% | 70% | medium |
