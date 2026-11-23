# Where Kalshi prices lag

*Built from minute-by-minute prices of markets that already settled. A **jump** is a move of 10¢+ within 5 minutes (news arriving). **Drift** is how much further the price kept moving the same way afterwards. **Follow** is the profit per $1 contract from betting with the jump one minute later, at the real ask price, after fees, held to settlement. **Fade** is betting against it. **Late** is buying the favourite an hour before close. Positive follow or drift = the market is slow there.*

178 markets and 121 jumps scanned since 2026-11-23.

## By category

| Category | Markets | Jumps | Drift 5 min | Drift 30 min | Drift 60 min | Follow | Fade | Late | Read |
|---|---|---|---|---|---|---|---|---|---|
| Crypto | 40 | 11 | -3.1¢ | -3.7¢ | -3.5¢ | +8.0¢ | -11.9¢ | +35.4¢ | early |
| Sports | 40 | 95 | +0.6¢ | +0.6¢ | +5.6¢ | -2.6¢ | -1.6¢ | -11.3¢ | keeps up |
| Climate and Weather | 17 | 13 | +4.6¢ | +4.5¢ | -6.0¢ | -8.1¢ | +1.4¢ | +0.9¢ | early |
| Politics | 4 | 2 | +1.0¢ | +5.3¢ | +9.5¢ | -26.8¢ | +19.6¢ | +1.9¢ | early |
| Elections | 4 | 0 | – | – | – | – | – | – | early |
| Commodities | 40 | 0 | – | – | – | – | – | – | early |
| Financials | 30 | 0 | – | – | – | – | – | – | early |
| Science and Technology | 1 | 0 | – | – | – | – | – | – | early |
| Entertainment | 1 | 0 | – | – | – | – | – | – | early |
| Economics | 1 | 0 | – | – | – | – | – | – | early |

## Market types where following a jump paid best

| Market type | Category | Jumps | Drift 30 min | Follow | Read |
|---|---|---|---|---|---|
| NFL Game (`KXNFLGAME`) | Sports | 11 | +3.9¢ | +17.2¢ | early |
| NBA Game (`KXNBAGAME`) | Sports | 11 | +4.1¢ | +13.5¢ | early |
| Pro Football Spread (`KXNFLSPREAD`) | Sports | 10 | -2.3¢ | +8.2¢ | early |
| Bitcoin price Above/below (`KXBTCD`) | Crypto | 11 | -3.7¢ | +8.0¢ | early |
| Challenger ATP  (`KXATPCHALLENGERMATCH`) | Sports | 11 | -6.9¢ | -7.2¢ | early |
| ITF Men's Match (`KXITFMATCH`) | Sports | 8 | -9.1¢ | -36.2¢ | early |

*Reads: **lags** = following jumps clearly paid; **drifts** = prices clearly kept moving, but not by enough to beat the spread and fees yet; **overreacts** = fading paid; **keeps up** = no clear edge; **early** = fewer than 30 jumps so far. "Clearly" means more than two standard errors from zero. Past patterns can fade, and this is pretend-money research, not financial advice.*
