# Where Kalshi prices lag

*Built from minute-by-minute prices of markets that already settled. A **jump** is a move of 10¢+ within 5 minutes (news arriving). **Drift** is how much further the price kept moving the same way afterwards. **Follow** is the profit per $1 contract from betting with the jump one minute later, at the real ask price, after fees, held to settlement. **Fade** is betting against it. **Late** is buying the favourite an hour before close. Positive follow or drift = the market is slow there.*

303 markets and 279 jumps scanned since 2026-11-23.

## By category

| Category | Markets | Jumps | Drift 5 min | Drift 30 min | Drift 60 min | Follow | Fade | Late | Read |
|---|---|---|---|---|---|---|---|---|---|
| Crypto | 60 | 15 | -3.3¢ | -1.4¢ | -3.5¢ | +8.7¢ | -12.7¢ | +35.4¢ | early |
| Economics | 21 | 59 | -0.1¢ | +0.4¢ | -0.2¢ | -2.9¢ | -2.4¢ | +3.5¢ | keeps up |
| Sports | 60 | 157 | +0.2¢ | -0.4¢ | +2.8¢ | -6.1¢ | +2.0¢ | -10.5¢ | keeps up |
| Politics | 6 | 5 | +1.4¢ | +4.0¢ | +6.7¢ | -12.4¢ | +6.1¢ | +17.6¢ | early |
| Climate and Weather | 37 | 43 | +2.5¢ | +1.2¢ | +3.4¢ | -12.9¢ | +5.2¢ | +0.9¢ | keeps up |
| Elections | 4 | 0 | – | – | – | – | – | – | early |
| Commodities | 60 | 0 | – | – | – | – | – | – | early |
| Financials | 50 | 0 | – | – | – | – | – | – | early |
| Science and Technology | 1 | 0 | – | – | – | – | – | – | early |
| Entertainment | 4 | 0 | – | – | – | – | – | – | early |

## Market types where following a jump paid best

| Market type | Category | Jumps | Drift 30 min | Follow | Read |
|---|---|---|---|---|---|
| NFL Game (`KXNFLGAME`) | Sports | 13 | +2.3¢ | +16.5¢ | early |
| Pro Football Spread (`KXNFLSPREAD`) | Sports | 13 | -0.6¢ | +12.8¢ | early |
| Bitcoin price Above/below (`KXBTCD`) | Crypto | 15 | -1.4¢ | +8.7¢ | early |
| ITF Women's Match (`KXITFWMATCH`) | Sports | 8 | +7.9¢ | +1.7¢ | early |
| Challenger ATP  (`KXATPCHALLENGERMATCH`) | Sports | 21 | -4.8¢ | -0.7¢ | early |
| NBA Game (`KXNBAGAME`) | Sports | 17 | +0.1¢ | -5.6¢ | early |
| Men's College Basketball Game (`KXNCAAMBGAME`) | Sports | 13 | -11.2¢ | -12.3¢ | early |
| Pro Football Total Points (`KXNFLTOTAL`) | Sports | 11 | +4.8¢ | -21.6¢ | early |
| ITF Men's Match (`KXITFMATCH`) | Sports | 11 | -6.0¢ | -25.8¢ | early |

*Reads: **lags** = following jumps clearly paid; **drifts** = prices clearly kept moving, but not by enough to beat the spread and fees yet; **overreacts** = fading paid; **keeps up** = no clear edge; **early** = fewer than 30 jumps so far. "Clearly" means more than two standard errors from zero. Past patterns can fade, and this is pretend-money research, not financial advice.*
