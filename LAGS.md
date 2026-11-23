# Where Kalshi prices lag

*Built from minute-by-minute prices of markets that already settled. A **jump** is a move of 10¢+ within 5 minutes (news arriving). **Drift** is how much further the price kept moving the same way afterwards. **Follow** is the profit per $1 contract from betting with the jump one minute later, at the real ask price, after fees, held to settlement. **Fade** is betting against it. **Late** is buying the favourite an hour before close. Positive follow or drift = the market is slow there.*

98 markets and 83 jumps scanned since 2026-11-23.

## By category

| Category | Markets | Jumps | Drift 5 min | Drift 30 min | Drift 60 min | Follow | Fade | Late | Read |
|---|---|---|---|---|---|---|---|---|---|
| Sports | 20 | 62 | +0.7¢ | +1.2¢ | +5.5¢ | -0.5¢ | -3.8¢ | -17.0¢ | keeps up |
| Crypto | 20 | 9 | -3.1¢ | +0.4¢ | -3.5¢ | -5.8¢ | +1.8¢ | +35.4¢ | early |
| Climate and Weather | 13 | 10 | +4.1¢ | -4.3¢ | -6.0¢ | -13.8¢ | +7.0¢ | +0.9¢ | early |
| Politics | 4 | 2 | +1.0¢ | +5.3¢ | +9.5¢ | -26.8¢ | +19.6¢ | +1.9¢ | early |
| Elections | 4 | 0 | – | – | – | – | – | – | early |
| Commodities | 20 | 0 | – | – | – | – | – | – | early |
| Financials | 15 | 0 | – | – | – | – | – | – | early |
| Science and Technology | 1 | 0 | – | – | – | – | – | – | early |
| Entertainment | 1 | 0 | – | – | – | – | – | – | early |

## Market types where following a jump paid best

| Market type | Category | Jumps | Drift 30 min | Follow | Read |
|---|---|---|---|---|---|
| NFL Game (`KXNFLGAME`) | Sports | 11 | +3.9¢ | +17.2¢ | early |
| Pro Football Spread (`KXNFLSPREAD`) | Sports | 10 | -2.3¢ | +8.2¢ | early |
| Bitcoin price Above/below (`KXBTCD`) | Crypto | 9 | +0.4¢ | -5.8¢ | early |
| ITF Men's Match (`KXITFMATCH`) | Sports | 8 | -9.1¢ | -36.2¢ | early |

*Reads: **lags** = following jumps clearly paid; **drifts** = prices clearly kept moving, but not by enough to beat the spread and fees yet; **overreacts** = fading paid; **keeps up** = no clear edge; **early** = fewer than 30 jumps so far. "Clearly" means more than two standard errors from zero. Past patterns can fade, and this is pretend-money research, not financial advice.*
