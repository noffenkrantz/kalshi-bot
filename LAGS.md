# Where Kalshi prices lag

*Built from minute-by-minute prices of markets that already settled. A **jump** is a move of 10¢+ within 5 minutes (news arriving). **Drift** is how much further the price kept moving the same way afterwards. **Follow** is the profit per $1 contract from betting with the jump one minute later, at the real ask price, after fees, held to settlement. **Fade** is betting against it. **Late** is buying the favourite an hour before close. Positive follow or drift = the market is slow there.*

625 markets and 534 jumps scanned since 2026-11-23.

## By category

| Category | Markets | Jumps | Drift 5 min | Drift 30 min | Drift 60 min | Follow | Fade | Late | Read |
|---|---|---|---|---|---|---|---|---|---|
| Politics | 14 | 17 | +0.6¢ | +2.9¢ | +5.8¢ | +26.8¢ | -34.7¢ | +11.6¢ | early |
| Financials | 107 | 20 | +5.9¢ | +2.6¢ | +8.0¢ | +4.6¢ | -11.2¢ | -6.2¢ | early |
| Mentions | 2 | 3 | +7.2¢ | +6.5¢ | +3.0¢ | -1.4¢ | -5.4¢ | – | early |
| Economics | 26 | 60 | -0.3¢ | +0.2¢ | -0.3¢ | -3.2¢ | -2.1¢ | +3.4¢ | keeps up |
| Sports | 120 | 306 | +0.1¢ | +0.3¢ | +2.3¢ | -3.4¢ | -0.8¢ | -8.0¢ | keeps up |
| Crypto | 120 | 32 | -0.5¢ | +3.2¢ | -1.0¢ | -7.2¢ | +3.3¢ | -13.7¢ | keeps up |
| Climate and Weather | 75 | 96 | +0.7¢ | +1.0¢ | -2.4¢ | -11.8¢ | +4.5¢ | +3.0¢ | overreacts |
| Elections | 28 | 0 | – | – | – | – | – | +0.9¢ | early |
| Commodities | 120 | 0 | – | – | – | – | – | – | early |
| Science and Technology | 4 | 0 | – | – | – | – | – | – | early |
| Entertainment | 9 | 0 | – | – | – | – | – | +0.9¢ | early |

## Market types where following a jump paid best

| Market type | Category | Jumps | Drift 30 min | Follow | Read |
|---|---|---|---|---|---|
| NFL Game (`KXNFLGAME`) | Sports | 17 | +0.4¢ | +20.3¢ | early |
| ITF Women's Match (`KXITFWMATCH`) | Sports | 30 | +7.8¢ | +7.1¢ | keeps up |
| NBA Spread (`KXNBASPREAD`) | Sports | 8 | +7.2¢ | +6.6¢ | early |
| Challenger ATP  (`KXATPCHALLENGERMATCH`) | Sports | 47 | -2.8¢ | +4.1¢ | keeps up |
| Pro Football Spread (`KXNFLSPREAD`) | Sports | 17 | -5.1¢ | +2.3¢ | early |
| NHL Game (`KXNHLGAME`) | Sports | 11 | +1.2¢ | +0.3¢ | early |
| NBA Game (`KXNBAGAME`) | Sports | 29 | -2.0¢ | -4.5¢ | early |
| Bitcoin price Above/below (`KXBTCD`) | Crypto | 32 | +3.2¢ | -7.2¢ | keeps up |
| Men's College Basketball Game (`KXNCAAMBGAME`) | Sports | 36 | -7.0¢ | -10.9¢ | keeps up |
| Pro Football Total Points (`KXNFLTOTAL`) | Sports | 11 | +4.8¢ | -21.6¢ | early |

## Market types where it paid worst

| Market type | Category | Jumps | Drift 30 min | Follow | Read |
|---|---|---|---|---|---|
| Hourly Directional Miami Temperature (`KXTEMPMIAH`) | Climate and Weather | 13 | +12.6¢ | -32.1¢ | early |
| ITF Men's Match (`KXITFMATCH`) | Sports | 14 | -7.5¢ | -25.8¢ | early |
| Dallas Maximum Temperature (`KXHIGHTDAL`) | Climate and Weather | 8 | -7.8¢ | -21.7¢ | early |
| Pro Football Total Points (`KXNFLTOTAL`) | Sports | 11 | +4.8¢ | -21.6¢ | early |
| Men's College Basketball Game (`KXNCAAMBGAME`) | Sports | 36 | -7.0¢ | -10.9¢ | keeps up |
| Bitcoin price Above/below (`KXBTCD`) | Crypto | 32 | +3.2¢ | -7.2¢ | keeps up |
| NBA Game (`KXNBAGAME`) | Sports | 29 | -2.0¢ | -4.5¢ | early |
| NHL Game (`KXNHLGAME`) | Sports | 11 | +1.2¢ | +0.3¢ | early |
| Pro Football Spread (`KXNFLSPREAD`) | Sports | 17 | -5.1¢ | +2.3¢ | early |
| Challenger ATP  (`KXATPCHALLENGERMATCH`) | Sports | 47 | -2.8¢ | +4.1¢ | keeps up |

*Reads: **lags** = following jumps clearly paid; **drifts** = prices clearly kept moving, but not by enough to beat the spread and fees yet; **overreacts** = fading paid; **keeps up** = no clear edge; **early** = fewer than 30 jumps so far. "Clearly" means more than two standard errors from zero. Past patterns can fade, and this is pretend-money research, not financial advice.*
