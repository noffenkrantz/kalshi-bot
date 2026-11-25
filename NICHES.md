# Slow, niche Kalshi markets

*Survey of 176,727 open markets and 325,666 that settled in the last 3 days (2026-11-25 02:52 UTC). For each market type: how busy and how tradable it is now, and, from a sample of settled markets' minute-by-minute prices, how often the price moved, how accurate it was before close, and whether buying the favourite late paid. Read-only research; not financial advice.*

**Columns:** *Price moves/h* = how often the best bid or ask changed per hour in the final day (low = slow). *Trades/h* = minutes with any trade per hour. *Spread* and *Depth* = the gap between bid and ask, and contracts on offer at the best price, on open markets now (a $100 bet needs roughly 100-300). *Error 6h* = squared gap between the price 6 hours before close and the result (0 = spot on, 0.25 = coin flip). *Fav 6h/1h* = profit per $1 from buying the favourite then at the ask, after fees. *Sample* = settled markets measured.

## Slowest market types you could actually trade

(Not sports or crypto; spread 6c or less and 50+ contracts on offer now.)

| Market type | Category | Open now | Price moves/h | Trades/h | Spread | Depth | Error 6h | Fav 6h | Fav 1h | Sample |
|---|---|---|---|---|---|---|---|---|---|---|
| Rotten Tomatoes Scores (`KXRT`) | Entertainment | 128 | 0.0 | 0.2 | 1.0¢ | 9,291 | – | – | – | 2 |
| How many album equivalent will album sell (`KXALBUMEQUIV`) | Entertainment | 64 | 0.0 | 0.0 | 4.0¢ | 52 | – | – | – | 4 |
| Boston Maximum Daily Temperature (`KXHIGHTBOS`) | Climate and Weather | 12 | 0.0 | 0.3 | 1.0¢ | 50 | – | – | – | 3 |
| Daily Diesel Price (`KXDIESELD`) | Economics | 21 | 0.3 | 0.2 | 1.5¢ | 1,042 | 0.000 | +0.9¢ | – | 3 |
| House Race Winner? (`KXHOUSERACE`) | Elections | 876 | 0.5 | 0.4 | 5.2¢ | 50 | 0.000 | +0.1¢ | +0.1¢ | 2 |
| Where will Jensen Huang work next? (`KXJOINJENSENHUANG`) | Financials | 23 | 2.8 | 8.8 | 4.0¢ | 100 | 0.633 | -80.0¢ | +5.6¢ | 2 |
| Oklahoma City Maximum High Temperature (`KXHIGHTOKC`) | Climate and Weather | 12 | 3.9 | 3.8 | 1.0¢ | 64 | – | – | – | 3 |
| Natural Gas Daily (`KXNATGASD`) | Commodities | 90 | 7.0 | 0.2 | 4.0¢ | 500 | 0.001 | +0.9¢ | – | 2 |
| Gold Daily (`KXGOLDD`) | Commodities | 40 | 8.9 | 0.7 | 2.0¢ | 525 | – | – | – | 2 |
| Washington DC Daily Max Temp (`KXHIGHTDC`) | Climate and Weather | 12 | 9.7 | 4.0 | 1.0¢ | 96 | – | – | – | 3 |
| Where will it rain daily (`KXRAIN`) | Climate and Weather | 74 | 12.9 | 14.8 | 1.0¢ | 116 | 0.416 | -67.6¢ | – | 2 |
| Daily Copper (`KXCOPPERD`) | Commodities | 50 | 16.7 | 0.6 | 4.0¢ | 500 | 0.001 | +2.8¢ | – | 2 |
| Brent Oil Daily (`KXBRENTD`) | Commodities | 20 | 18.0 | 1.8 | 3.0¢ | 300 | 0.007 | +6.6¢ | +0.9¢ | 2 |
| Hourly Directional Miami Temperature (`KXTEMPMIAH`) | Climate and Weather | 10 | 23.0 | 18.0 | 1.0¢ | 51 | – | – | – | 4 |
| INXDUD (`KXINXDUD`) | Financials | 1 | 23.3 | 7.1 | 4.0¢ | 101 | 0.074 | +18.6¢ | +0.9¢ | 2 |
| Silver daily (`KXSILVERD`) | Commodities | 40 | 26.2 | 4.5 | 2.0¢ | 500 | 0.044 | +19.4¢ | +10.8¢ | 2 |
| DJI Hourly (`KXDJI`) | Financials | 77 | 32.0 | 1.4 | 4.0¢ | 2,100 | 0.302 | -58.7¢ | -18.0¢ | 2 |
| Gold Hourly (`KXGOLDH`) | Commodities | 162 | 45.0 | 10.4 | 5.0¢ | 50 | – | – | – | 3 |

## Where prices were least accurate 6 hours before close (tradable types)

| Market type | Category | Error 6h | Error 1h | Fav 6h | Price moves/h | Sample |
|---|---|---|---|---|---|---|
| NBA Total Points Range (`KXNBATOTALPRECISE`) | Sports | 0.866 | – | -97.2¢ | 2.6 | 2 |
| 1st Half Total (`KXBRASILEIRO1HTOTAL`) | Sports | 0.656 | 0.656 | -82.0¢ | 2.2 | 2 |
| Where will Jensen Huang work next? (`KXJOINJENSENHUANG`) | Financials | 0.633 | 0.005 | -80.0¢ | 2.8 | 2 |
| 1st Half BTTS (`KXEFLCHAMPIONSHIP1HBTTS`) | Sports | 0.620 | 0.632 | -80.6¢ | 1.9 | 2 |
| Point Total (`KXDIMAYORTOTAL`) | Sports | 0.567 | 0.092 | -77.3¢ | 2.9 | 2 |
| Eliteserien Game (`KXELITESERIENGAME`) | Sports | 0.487 | 0.315 | -70.9¢ | 3.7 | 2 |
| Ecuador Liga Pro Game (`KXECULPGAME`) | Sports | 0.478 | 0.342 | -69.9¢ | 2.7 | 2 |
| NBA 2nd Half Total (`KXNBA2HTOTAL`) | Sports | 0.476 | 0.413 | -72.9¢ | 17.0 | 2 |
| English Premier League Spread (`KXEPLSPREAD`) | Sports | 0.442 | 0.009 | -68.5¢ | 2.0 | 2 |
| Czech First League Game (`KXCZEFLGAME`) | Sports | 0.437 | 0.289 | -67.5¢ | 3.3 | 2 |
| Where will it rain daily (`KXRAIN`) | Climate and Weather | 0.416 | – | -67.6¢ | 12.9 | 2 |
| Pro Football 3rd Quarter Winner (`KXNFL3Q`) | Sports | 0.415 | 0.362 | -24.8¢ | 4.9 | 2 |
| 1st Half Winner (`KXEFLCHAMPIONSHIP1H`) | Sports | 0.367 | 0.381 | -20.9¢ | 2.4 | 2 |
| Point Total (`KXENGNLTOTAL`) | Sports | 0.364 | 0.089 | -29.2¢ | 4.0 | 2 |
| EPL Both Teams to Score (`KXEPLBTTS`) | Sports | 0.361 | 0.109 | -62.2¢ | 4.3 | 2 |
| Bundesliga Spread (`KXBUNDESLIGASPREAD`) | Sports | 0.345 | 0.141 | -42.0¢ | 2.5 | 2 |
| 1st Half Correct Score (`KXMLS1HSCORE`) | Sports | 0.335 | 0.656 | -36.8¢ | 3.1 | 2 |
| 2nd Half Winner (`KXMLS2H`) | Sports | 0.333 | 0.436 | -61.6¢ | 5.4 | 2 |
| Pro Football 1st Quarter Winner (`KXNFL1Q`) | Sports | 0.328 | 0.329 | -31.1¢ | 1.4 | 2 |
| Pro Football 3rd Quarter Total (`KXNFL3QTOTAL`) | Sports | 0.324 | 0.319 | -34.5¢ | 9.2 | 2 |
| BTTS (`KXDIMAYORBTTS`) | Sports | 0.317 | 0.182 | -58.7¢ | 2.8 | 2 |
| 1st Half Winner (`KXAFCCL1H`) | Sports | 0.312 | 0.317 | -8.2¢ | 2.6 | 2 |
| DJI Hourly (`KXDJI`) | Financials | 0.302 | 0.177 | -58.7¢ | 32.0 | 2 |
| 1st Half BTTS (`KXAFCCL1HBTTS`) | Sports | 0.301 | 0.306 | -28.2¢ | 1.9 | 2 |
| Argentina Premier Division BTTS (`KXARGPREMDIVBTTS`) | Sports | 0.300 | 0.255 | -57.2¢ | 2.1 | 2 |

## By category (median of market types)

| Category | Types sampled | Tradable now | Price moves/h | Trades/h | Error 6h | Fav 6h |
|---|---|---|---|---|---|---|
| Entertainment | 7 | 2 | 0.0 | 0.0 | – | – |
| Elections | 7 | 1 | 0.0 | 0.0 | 0.002 | +1.0¢ |
| Science and Technology | 1 | 0 | 1.1 | 0.1 | – | – |
| Economics | 52 | 1 | 2.4 | 0.5 | 0.004 | +3.7¢ |
| Politics | 3 | 0 | 2.9 | 1.2 | 0.060 | +0.9¢ |
| Sports | 511 | 137 | 4.0 | 1.1 | 0.157 | +4.7¢ |
| Climate and Weather | 54 | 5 | 4.2 | 1.3 | 0.004 | +0.9¢ |
| Financials | 15 | 3 | 17.9 | 1.0 | 0.287 | -13.6¢ |
| Commodities | 10 | 6 | 26.5 | 3.1 | 0.004 | +4.7¢ |
| Crypto | 10 | 5 | 43.2 | 12.2 | 0.034 | +14.1¢ |

*Small samples per type (2-4 markets) make single numbers noisy; treat this as a shortlist to test, not a verdict.*
