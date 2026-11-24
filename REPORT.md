# Kalshi bot report - 2026-11-24T03:18:19+00:00

## SHADOW
Forecasts: 29 made, 18 resolved
Accuracy (Brier, lower is better): Claude 0.2870 vs market price 0.2024 -> Claude is WORSE than the market
When Claude disagreed with the market by 8%+: Claude was closer 3 of 12 times
Calibration (when Claude says X%, how often is it YES?):
  0%-20%:   5 forecasts, avg said 7%, actually YES 20%
  20%-40%:   3 forecasts, avg said 27%, actually YES 67%
  40%-60%:   6 forecasts, avg said 44%, actually YES 33%
  80%-100%:   4 forecasts, avg said 94%, actually YES 50%
Paper trades (at real prices, assuming fills at the ask): 1 total, 1 settled, 0 won, P&L on settled ~$-99.97
Real balance (settled bets only): $9,900.03; projected with moved open bets at today's prices: $9,900.03

## Where Claude does well (simulation, settled forecasts)

**By topic**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| Climate and Weather | 11 | 0.331 | 0.200 | 1 of 7 |
| Politics | 4 | 0.103 | 0.216 | 2 of 3 |
| Economics | 3 | 0.371 | 0.193 | 1 of 3 |

**By Claude's confidence**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| medium | 10 | 0.237 | 0.120 | 2 of 7 |
| low | 3 | 0.194 | 0.307 | 1 of 2 |
| medium-high | 2 | 0.388 | 0.298 | 1 of 2 |
| medium-low | 2 | 0.248 | 0.080 | 0 of 1 |
| high | 1 | 0.941 | 0.766 | 0 of 1 |

**By distance from the market price**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| 5–15 pts from market | 7 | 0.425 | 0.321 | 2 of 7 |
| 15+ pts from market | 6 | 0.300 | 0.160 | 2 of 6 |
| within 5 pts of market | 5 | 0.079 | 0.088 | – |

(Scores are Brier scores: lower is better.)

**Do the lessons help?** (about 20% of markets are researched without lessons, as a control)
With lessons: 0.193 on 8 forecasts · without: 0.198 on 6. Lessons look helpful so far. Small samples are noisy.

Claude API spend: ~$4.43 in the last 7 days, ~$4.43 all time

## Verdict
Not enough data yet: 18/100 shadow forecasts have resolved. Keep collecting before drawing conclusions.

## Latest forecasts

| When (UTC) | Market | Claude | Market price | Confidence |
|---|---|---|---|---|
| 2026-11-24T03:17 | S&P price on Nov 24, 2026 at 4pm EST? — 7,235 or above | 50% | 57% | medium-low |
| 2026-11-24T01:12 | S&P price on Nov 24, 2026 at 4pm EST? — 7,095 or above | 76% | 94% | medium-low |
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
