# Kalshi bot report - 2026-11-23T03:12:28+00:00

## SHADOW
Forecasts: 23 made, 3 resolved
Accuracy (Brier, lower is better): Claude 0.0874 vs market price 0.2324 -> Claude is BETTER than the market
When Claude disagreed with the market by 8%+: Claude was closer 1 of 2 times
Calibration (when Claude says X%, how often is it YES?):
  0%-20%:   1 forecasts, avg said 11%, actually YES 0%
  20%-40%:   1 forecasts, avg said 30%, actually YES 0%
  40%-60%:   1 forecasts, avg said 40%, actually YES 0%
Paper trades (at real prices, assuming fills at the ask): 1 total, 0 settled, 0 won, P&L on settled ~$+0.00
Account value: $10,000.00 at first run -> $9,928.19 now

## Where Claude does well (simulation, settled forecasts)

**By topic**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| Politics | 2 | 0.125 | 0.334 | 1 of 2 |
| Climate and Weather | 1 | 0.012 | 0.029 | 1 of 1 |

**By Claude's confidence**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| medium | 2 | 0.086 | 0.048 | 1 of 2 |
| low | 1 | 0.090 | 0.601 | 1 of 1 |

**By distance from the market price**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| 5–15 pts from market | 2 | 0.086 | 0.048 | 1 of 2 |
| 15+ pts from market | 1 | 0.090 | 0.601 | 1 of 1 |

(Scores are Brier scores: lower is better.)

**Do the lessons help?** (about 20% of markets are researched without lessons, as a control)
With lessons: 0.012 on 1 forecasts · without: 0.125 on 2. Lessons look helpful so far. Small samples are noisy.

Claude API spend: ~$3.46 in the last 7 days, ~$3.46 all time

## Verdict
Not enough data yet: 3/100 shadow forecasts have resolved. Keep collecting before drawing conclusions.

## Latest forecasts

| When (UTC) | Market | Claude | Market price | Confidence |
|---|---|---|---|---|
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
| 2026-11-21T21:40 | Lowest temperature in Newark on Nov 22, 2026? — 45° to 46° | 5% | 6% | medium |
| 2026-11-21T21:40 | Highest temperature in Miami on Nov 22, 2026? — 83° to 84° | 45% | 30% | medium |
| 2026-11-21T21:40 | Where will it rain on Nov 22, 2026? — Newark | 92% | 92% | medium |
| 2026-11-21T21:40 | Trump's RCP approval average on Nov 22, 2026? — 38.4% | 40% | 26% | medium |
