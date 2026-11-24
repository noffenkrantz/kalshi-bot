# Where Kalshi prices lag

*Built from minute-by-minute prices of markets that already settled. A **jump** is a move of 10¢+ within 5 minutes (news arriving). **Drift** is how much further the price kept moving the same way afterwards. **Follow** is the profit per $1 contract from betting with the jump one minute later, at the real ask price, after fees, held to settlement. **Fade** is betting against it. **Late** is buying the favourite an hour before close. Positive follow or drift = the market is slow there.*

521 markets and 438 jumps scanned since 2026-11-23.

## By category

| Category | Markets | Jumps | Drift 5 min | Drift 30 min | Drift 60 min | Follow | Fade | Late | Read |
|---|---|---|---|---|---|---|---|---|---|
| Politics | 13 | 14 | +0.9¢ | +3.6¢ | +5.4¢ | +19.5¢ | -27.8¢ | +9.3¢ | early |
| Financials | 87 | 20 | +5.9¢ | +2.6¢ | +8.0¢ | +4.6¢ | -11.2¢ | -6.2¢ | early |
| Mentions | 2 | 3 | +7.2¢ | +6.5¢ | +3.0¢ | -1.4¢ | -5.4¢ | – | early |
| Economics | 24 | 59 | -0.1¢ | +0.4¢ | -0.2¢ | -2.9¢ | -2.4¢ | +3.4¢ | keeps up |
| Sports | 100 | 257 | +0.2¢ | +0.9¢ | +1.6¢ | -2.9¢ | -1.1¢ | -8.9¢ | keeps up |
| Crypto | 100 | 26 | -3.2¢ | -1.8¢ | -1.0¢ | -6.0¢ | +2.0¢ | -13.7¢ | early |
| Climate and Weather | 55 | 59 | +1.8¢ | +2.3¢ | +3.4¢ | -12.8¢ | +5.3¢ | +0.9¢ | keeps up |
| Elections | 28 | 0 | – | – | – | – | – | +0.9¢ | early |
| Commodities | 100 | 0 | – | – | – | – | – | – | early |
| Science and Technology | 4 | 0 | – | – | – | – | – | – | early |
| Entertainment | 8 | 0 | – | – | – | – | – | +0.9¢ | early |

## Market types where following a jump paid best

| Market type | Category | Jumps | Drift 30 min | Follow | Read |
|---|---|---|---|---|---|
| NFL Game (`KXNFLGAME`) | Sports | 13 | +2.3¢ | +16.5¢ | early |
| Pro Football Spread (`KXNFLSPREAD`) | Sports | 13 | -0.6¢ | +12.8¢ | early |
| Challenger ATP  (`KXATPCHALLENGERMATCH`) | Sports | 38 | -3.7¢ | +11.7¢ | keeps up |
| NBA Spread (`KXNBASPREAD`) | Sports | 8 | +7.2¢ | +6.6¢ | early |
| ITF Women's Match (`KXITFWMATCH`) | Sports | 22 | +8.1¢ | +3.0¢ | early |
| NBA Game (`KXNBAGAME`) | Sports | 23 | +1.7¢ | -3.7¢ | early |
| NHL Game (`KXNHLGAME`) | Sports | 9 | +2.6¢ | -4.7¢ | early |
| Bitcoin price Above/below (`KXBTCD`) | Crypto | 26 | -1.8¢ | -6.0¢ | early |
| Men's College Basketball Game (`KXNCAAMBGAME`) | Sports | 33 | -8.5¢ | -14.8¢ | keeps up |
| Pro Football Total Points (`KXNFLTOTAL`) | Sports | 11 | +4.8¢ | -21.6¢ | early |

## Market types where it paid worst

| Market type | Category | Jumps | Drift 30 min | Follow | Read |
|---|---|---|---|---|---|
| Hourly Directional Miami Temperature (`KXTEMPMIAH`) | Climate and Weather | 11 | +13.5¢ | -31.1¢ | early |
| ITF Men's Match (`KXITFMATCH`) | Sports | 11 | -6.0¢ | -25.8¢ | early |
| Pro Football Total Points (`KXNFLTOTAL`) | Sports | 11 | +4.8¢ | -21.6¢ | early |
| Men's College Basketball Game (`KXNCAAMBGAME`) | Sports | 33 | -8.5¢ | -14.8¢ | keeps up |
| Bitcoin price Above/below (`KXBTCD`) | Crypto | 26 | -1.8¢ | -6.0¢ | early |
| NHL Game (`KXNHLGAME`) | Sports | 9 | +2.6¢ | -4.7¢ | early |
| NBA Game (`KXNBAGAME`) | Sports | 23 | +1.7¢ | -3.7¢ | early |
| ITF Women's Match (`KXITFWMATCH`) | Sports | 22 | +8.1¢ | +3.0¢ | early |
| NBA Spread (`KXNBASPREAD`) | Sports | 8 | +7.2¢ | +6.6¢ | early |
| Challenger ATP  (`KXATPCHALLENGERMATCH`) | Sports | 38 | -3.7¢ | +11.7¢ | keeps up |

*Reads: **lags** = following jumps clearly paid; **drifts** = prices clearly kept moving, but not by enough to beat the spread and fees yet; **overreacts** = fading paid; **keeps up** = no clear edge; **early** = fewer than 30 jumps so far. "Clearly" means more than two standard errors from zero. Past patterns can fade, and this is pretend-money research, not financial advice.*
