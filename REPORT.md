# Kalshi bot report - 2026-11-24T14:24:39+00:00

## SHADOW
Forecasts: 33 made, 22 resolved
Accuracy (Brier, lower is better): Claude 0.2770 vs market price 0.1833 -> Claude is WORSE than the market
When Claude disagreed with the market by 8%+: Claude was closer 4 of 15 times
Calibration (when Claude says X%, how often is it YES?):
  0%-20%:   7 forecasts, avg said 8%, actually YES 14%
  20%-40%:   4 forecasts, avg said 26%, actually YES 75%
  40%-60%:   7 forecasts, avg said 45%, actually YES 29%
  80%-100%:   4 forecasts, avg said 94%, actually YES 50%
Paper trades (at real prices, assuming fills at the ask): 1 total, 1 settled, 0 won, P&L on settled ~$-99.97
Real balance (settled bets only): $9,900.03; projected with moved open bets at today's prices: $9,900.03

## Where Claude does well (simulation, settled forecasts)

**By topic**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| Climate and Weather | 13 | 0.330 | 0.197 | 2 of 9 |
| Economics | 5 | 0.277 | 0.122 | 1 of 4 |
| Politics | 4 | 0.103 | 0.216 | 2 of 3 |

**By Claude's confidence**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| medium | 13 | 0.233 | 0.121 | 3 of 9 |
| low | 3 | 0.194 | 0.307 | 1 of 2 |
| medium-low | 3 | 0.256 | 0.061 | 0 of 2 |
| medium-high | 2 | 0.388 | 0.298 | 1 of 2 |
| high | 1 | 0.941 | 0.766 | 0 of 1 |

**By distance from the market price**

| Group | Forecasts | Claude score | Market score | Claude beat market when they disagreed |
|---|---|---|---|---|
| 15+ pts from market | 9 | 0.302 | 0.149 | 3 of 9 |
| 5–15 pts from market | 7 | 0.425 | 0.321 | 2 of 7 |
| within 5 pts of market | 6 | 0.066 | 0.075 | – |

(Scores are Brier scores: lower is better.)

**Do the lessons help?** (about 20% of markets are researched without lessons, as a control)
With lessons: 0.206 on 12 forecasts · without: 0.198 on 6. No sign yet that lessons help. Small samples are noisy.

Claude API spend: ~$5.15 in the last 7 days, ~$5.15 all time

## Verdict
Not enough data yet: 22/100 shadow forecasts have resolved. Keep collecting before drawing conclusions.

## Latest forecasts

| When (UTC) | Market | Claude | Market price | Confidence |
|---|---|---|---|---|
| 2026-11-24T14:22 | Diesel prices tomorrow — Above $5.765 | 47% | 30% | medium-low |
| 2026-11-24T14:22 | Where will it rain on Nov 25, 2026? — Washington DC | 10% | 21% | medium-high |
| 2026-11-24T14:22 | Copper price on Nov 25, 2026 at 5:00 PM EST? — Above $5.60 | 23% | 24% | medium-low |
| 2026-11-24T14:22 | US gas prices tomorrow — Above 3.5900 | 88% | 64% | medium-high |
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
