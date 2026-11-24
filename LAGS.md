# Where Kalshi prices lag

*Built from minute-by-minute prices of markets that already settled. A **jump** is a move of 10¢+ within 5 minutes (news arriving). **Drift** is how much further the price kept moving the same way afterwards. **Follow** is the profit per $1 contract from betting with the jump one minute later, at the real ask price, after fees, held to settlement. **Fade** is betting against it. **Late** is buying the favourite an hour before close. Positive follow or drift = the market is slow there.*

430 markets and 381 jumps scanned since 2026-11-23.

## By category

| Category | Markets | Jumps | Drift 5 min | Drift 30 min | Drift 60 min | Follow | Fade | Late | Read |
|---|---|---|---|---|---|---|---|---|---|
| Politics | 12 | 14 | +0.9¢ | +3.6¢ | +5.4¢ | +19.5¢ | -27.8¢ | +10.6¢ | early |
| Financials | 70 | 20 | +5.9¢ | +2.6¢ | +8.0¢ | +4.6¢ | -11.2¢ | -6.2¢ | early |
| Crypto | 80 | 24 | -0.9¢ | -1.9¢ | -1.0¢ | -0.6¢ | -3.4¢ | -13.7¢ | early |
| Economics | 24 | 59 | -0.1¢ | +0.4¢ | -0.2¢ | -2.9¢ | -2.4¢ | +3.4¢ | keeps up |
| Sports | 80 | 210 | -0.0¢ | +0.6¢ | +1.0¢ | -4.9¢ | +0.7¢ | -15.1¢ | keeps up |
| Climate and Weather | 49 | 54 | +2.3¢ | +1.4¢ | +3.4¢ | -14.5¢ | +7.0¢ | +0.9¢ | overreacts |
| Elections | 24 | 0 | – | – | – | – | – | +0.9¢ | early |
| Commodities | 80 | 0 | – | – | – | – | – | – | early |
| Science and Technology | 4 | 0 | – | – | – | – | – | – | early |
| Entertainment | 7 | 0 | – | – | – | – | – | +0.9¢ | early |

## Market types where following a jump paid best

| Market type | Category | Jumps | Drift 30 min | Follow | Read |
|---|---|---|---|---|---|
| NFL Game (`KXNFLGAME`) | Sports | 13 | +2.3¢ | +16.5¢ | early |
| Pro Football Spread (`KXNFLSPREAD`) | Sports | 13 | -0.6¢ | +12.8¢ | early |
| Challenger ATP  (`KXATPCHALLENGERMATCH`) | Sports | 31 | -5.5¢ | +9.5¢ | keeps up |
| ITF Women's Match (`KXITFWMATCH`) | Sports | 16 | +12.3¢ | +6.8¢ | early |
| Bitcoin price Above/below (`KXBTCD`) | Crypto | 24 | -1.9¢ | -0.6¢ | early |
| NBA Game (`KXNBAGAME`) | Sports | 17 | +0.1¢ | -5.6¢ | early |
| Men's College Basketball Game (`KXNCAAMBGAME`) | Sports | 24 | -10.6¢ | -20.8¢ | early |
| Pro Football Total Points (`KXNFLTOTAL`) | Sports | 11 | +4.8¢ | -21.6¢ | early |
| ITF Men's Match (`KXITFMATCH`) | Sports | 11 | -6.0¢ | -25.8¢ | early |
| Hourly Directional Miami Temperature (`KXTEMPMIAH`) | Climate and Weather | 10 | +15.8¢ | -29.9¢ | early |

*Reads: **lags** = following jumps clearly paid; **drifts** = prices clearly kept moving, but not by enough to beat the spread and fees yet; **overreacts** = fading paid; **keeps up** = no clear edge; **early** = fewer than 30 jumps so far. "Clearly" means more than two standard errors from zero. Past patterns can fade, and this is pretend-money research, not financial advice.*
