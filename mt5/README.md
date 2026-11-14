# MT5 Backtest Analyzer - `MT5_Backtest_Analyzer.html`

A single HTML file (no install, no internet, nothing uploaded). Download it, open it in a browser and drop in:
- an MT5 **Strategy Tester journal log** (`Tester\logs\*.log` or `Tester\Agent-*\logs\*.log`, UTF-16 or UTF-8; or paste the Journal
  tab text), or the tester-style logs from `backtest/mt5_tester_log.py`, or
- an MT5 **Strategy Tester report** saved as HTML (Backtest tab -> right-click -> Report -> HTML).

It rebuilds every trade from the deals and shows: net PnL, return %, final balance, win rate (also excluding breakeven),
profit factor, expectancy, average win / loss and payoff, largest win / loss, streaks, max drawdown (money, % and duration),
recovery factor, Sharpe per trade, total / average R, max drawdown in R, SQN, trades per weekday, holding time; long vs short,
exit reasons (TP / SL / BE / trail / close), monthly, by entry hour and by weekday; balance + drawdown chart, monthly and hourly
bars, R distribution; a sortable, filterable trade list with CSV export.

Journal logs have no money per deal, so profit = price move x lots x *value per lot per 1.0 move* (guessed from the symbol:
indices 1, gold 100, xxxUSD FX 100000 - check it) minus a *cost per lot* solved so the total matches the log's final balance.
HTML reports and `mt5_tester_log.py` logs carry their own profit. Account type (hedging / netting) and breakeven tolerance can be set.

---

# ICT ERL/IRL EA (MetaTrader 5) - `ICT_ERL_IRL_EA.mq5`

A separate EA for the **ERL / IRL model** - the same rules as the TradingView *ICT ERL/IRL* scripts and the Python
backtest `intraday_snap.py` with `ERL_IRL=1`. It is built from the intraday EA below and differs only here (short described):

- **ERL starts a setup:** D/W/M swings, 4H and 1H swings, Asia/London/NY session highs/lows, ICT macro highs/lows.
  FVG edges are **not** swept as liquidity.
- **IRL:** fresh D / 4H / 1H FVGs (`InpIrlD`, `InpIrl4H`, `InpIrl1H`). A short needs a fresh **bullish** FVG below the
  entry at least `InpIrlMinR` (1R) away; none -> the order is not placed (`InpIrlRequired`; false = first target `InpTargetR`).
- **TP1 = that IRL** (its near edge; `InpIrlCE` = its 50%). When price reaches it the EA closes `InpPartialPct` (50 %) at
  market and moves the stop to breakeven. The first-target price is saved at order placement in the terminal global
  variable `ICTERL_TP1_<order ticket>` (the position keeps that ticket as its identifier), so restarts keep it.
- **Broker TP = the next ERL:** the nearest unswept D/W/M/4H/1H swing low or session low below TP1 (macros not used).
  None -> the broker TP is TP1 and everything closes there.
- Everything else as the intraday EA: sweep rule, IFVG, BOS/MSS, displacement, bias, entry FVG/VI, breaker stop, 60-minute
  order, one trade per entry, flat 15 min before the 17:00 NY close, loss limits, real-account lock.
- **Own magic number 770201** (intraday EA: 770101), order comments `ICTe S/L <time>`, global variables `ICTERL_*`, so both
  EAs can run on the same account and symbol without touching each other's trades.

**Not compiled or tested here.** Compile it (F7), send me any errors, then use the Strategy Tester / demo. The Python
backtest of these rules lost money in October 2026 (Exness -25.4R, GOAT -35.8R, Pepperstone -36.5R).

---

# ICT Intraday EA (MetaTrader 5) - `ICT_Intraday_EA.mq5`

An Expert Advisor for the **intraday model only** (US100, 5m), with the same rules as the intraday TradingView scripts and
the Python backtest (`backtest/intraday_snap.py`). The swing EA is described further down.

## Status - read this first
- **Not compiled or tested here** (no MetaEditor / Strategy Tester in this environment). Brackets and calls were checked
  by script only. Compile it in MetaEditor (F7), send me any compiler errors, then run it in the Strategy Tester and on demo.
- **The model loses money in the backtest** (Exness US100, Oct 2026: 58 trades, -21.6R after costs; 2024-2026 with the bias
  filter: about -313R / -347R). Do not run it live on these rules.
- Fully automatic by default; REAL accounts stay signals-only unless `InpAllowRealAccount = true`.

## Install
1. Copy `ICT_Intraday_EA.mq5` to `MQL5/Experts/`, open it in MetaEditor, press F7.
2. Attach it to a **US100** chart (any timeframe; it reads M5 and H1 itself). Make sure the terminal has enough M5 and H1
   history (Tools -> Options -> Charts -> Max bars; scroll the H1 chart back).
3. **Set `InpServerGMT`** to your broker's server offset from UTC (Exness = 0; most brokers that close the day at
   17:00 New York = 2 in winter / 3 in summer). Live it is detected automatically (`InpAutoGMT`), but the **Strategy Tester
   uses `InpServerGMT`**. Sessions, ICT macro windows and the D/W/M/4H candles are all on New York time, so a wrong offset
   shifts every one of them.
4. Strategy Tester: symbol US100, any timeframe, "Every tick" or "1 minute OHLC".

## What it does on every completed 5m candle (short; long mirrored)
1. **Liquidity:** D/W/M swings (2 each side), 4H and 1H swings (10 each side), fresh D, 4H and 1H FVG far edges (D added in v1.30, `InpFvgLiqD`), Asia
   (20-24 NY) / London (2-5) / NY (7-10) session highs/lows that are also 1H+ swings (valid 7 days), ICT macro window
   highs/lows (valid 24 h). D/W/M/4H candles are built from 1H on New York time (day rolls 17:00 NY, 4H grid NY+7h), like the backtest.
2. **Sweep (5m):** (A) wick through + close back, or (B) 1-2 closes beyond then two displacement candles (>= 1 ATR14), the
   second closing beyond the first sweeping candle's low. A level is used up by its first sweep.
3. **Bias:** the last D/W/M/4H/1H swing sweep (high swept = shorts only). Sessions, FVG edges and macros don't set it.
4. **IFVG:** the intact 5m or 15m FVG nearest to the sweep, completed in the 48 5m candles before it.
5. **Reversal within 48 candles:** a 5m close through the FVG **and** a break (close or wick) of the leg-origin low or the
   post-sweep 5m MSS low, with displacement (2 candles >= 1 ATR, or one body >= 1 ATR) on the completing candle.
6. **Stop:** the high of the 5m breaker (last bearish candle at/before the broken low, 10 back), no buffer, no minimum.
7. **Entry:** sell limit at the bottom of the latest bearish 5m FVG or volume imbalance of the drop from the sweep extreme
   (may complete up to 2 candles after the reversal; a newer zone replaces the order while it is unfilled). Valid 60 min
   after the reversal close; cancelled when a 5m candle opens above the stop. If price is already through the limit it enters
   at market. One trade per entry zone / price.
8. **Exit (v1.10, `InpPartial`, default on):** the broker TP is the **next Rule 1 swing** - the nearest D/W/M/4H/1H swing low
   (short) below the 3R price that is not swept yet. When price reaches **3R** (`InpTargetR`) the EA closes **50 %**
   (`InpPartialPct`) at market and moves the stop on the rest to **breakeven**; the rest runs to that swing. No such swing ->
   the TP is 3R and everything closes there. If the volume can't be split (minimum lot), the whole position is closed at 3R.
   The +1R breakeven is **off** in this mode unless `InpBEBeforeTP1 = true`. The first target is stored per position in a
   terminal global variable (`ICTINTRA_TP1_<ticket>`), so a restart keeps it. `InpPartial = false` = the old exits
   (everything at 3R or the major 5m swing, breakeven at +1R).
9. **End of day (v1.20, `InpEODClose`, default on):** from **15 min before the market close** (`InpEODMin`, close time
   `InpEODCloseNY` = 17:00 New York, the US100 CFD daily close, every day incl. Friday) the EA closes all its positions at
   market, cancels its pending orders and places no new ones until the market reopens. Use "16:00" for the cash close.
   Needs the right `InpServerGMT` in the Strategy Tester (the cutoff is on New York time).

At start it replays the 1H history (levels already swept = a 1H wick through + close back) and the last `InpWarmupDays`
(30) of 5m candles without trading, so the bias, used-up levels and any still-valid order are known; an existing pending
order with the same comment (`ICTi S/L <reversal time>`) is adopted. The chart comment shows the bias, live levels,
waiting sweeps, pending/open model trades and the model's R since start. Safety inputs (daily loss, max drawdown, max
spread, real-account lock, `InpMaxOpen`) work as in the swing EA. Netting accounts: one order/position at a time.

## Known differences from the Python backtest
- Before the 5m warm-up, levels count as swept by a 1H wick + close back (the backtest uses 5m candles throughout).
- Session highs/lows: the backtest checks the 1H+ swing filter against all swings, including later ones; the EA activates a
  session level only once a matching swing exists (up to 7 days).
- The entry zone is refined live: if the first zone fills before a newer one completes (up to 2 candles), the EA keeps the
  first fill; the backtest uses the final zone.
- Breakeven is set after the candle closes; the broker may also hit the target on the fill candle (the backtest does not).
- Spread / slippage are real; the backtest used a fixed cost per trade.

---

# ICT Swing EA (MetaTrader 5)

`ICT_Swing_EA.mq5` — an Expert Advisor for the **swing model** (US100). It follows the same rules as the TradingView
scripts and the Python backtest.

## Status — read this first
- **Not tested in MT5.** I could not run MetaEditor or the Strategy Tester here, so this code has been checked by
  reading it (brackets, identifiers, call structure) but **not compiled or backtested**. Compile it in MetaEditor
  first and fix anything the compiler reports (send me the errors and I will fix them).
- It is a **faithful-in-spirit port, not an exact one** (see "Known differences"). Expect results to differ from the
  backtest.
- **Fully automatic by default** (`InpLiveTrading = true`): it places the limit order, cancels it when invalid or
  expired, sizes the lot from your risk %, and moves the stop to breakeven. 
- **Real-account lock:** on a REAL account it stays in signals-only mode unless you set `InpAllowRealAccount = true`.
  Demo and prop-firm evaluation accounts trade automatically. **Run it on a demo account first.**

## Automation safeguards
| Safeguard | Input | Default |
|---|---|---|
| One swing order/position at a time | `InpOneTradeAtATime` | on |
| Skip placing while the spread is wide | `InpMaxSpread` (price units) | 8.0 |
| Daily loss limit: no new trades, pending orders cancelled | `InpDailyLossPct` | 4 % |
| Max drawdown from the equity peak (stored across restarts): EA halts | `InpMaxDrawdownPct` | 8 % |
| Also close open positions when a limit is hit | `InpFlattenOnLimit` | off |
| Resume after a drawdown halt: set true for one start, then back to false | `InpResetPeak` | off |
| Real-account lock | `InpAllowRealAccount` | off |

It also: checks the broker's minimum stop distance and free margin before ordering; falls back to a GTC order if the
broker rejects order expiry; enters at market if price is already at or through the entry (the backtest fills on touch);
refuses to trade if the risk budget is below the minimum lot (it never over-risks); and recovers an existing order or
position after a restart or recompile. Set the two loss limits to match your prop firm's rules (they should be tighter
than the firm's own limits).

## Install
1. MT5 -> File -> Open Data Folder -> `MQL5/Experts/`, copy `ICT_Swing_EA.mq5` there.
2. Open it in MetaEditor, press F7 (Compile). It should compile with no errors.
3. Attach to a **US100** chart (NAS100 / USTEC / etc.) on any timeframe (it reads 1H/4H/D/W/MN itself).
4. Make sure the chart has enough history for D/W/MN/4H/1H (Tools -> Options -> Charts -> Max bars; scroll back once).

## The rules it implements (short; long is mirrored)
1. **Liquidity (Rule 1):** unbroken swing highs/lows on **D / W / M** (2 candles each side) and **4H** (10 each side), plus the **far edge of every fresh 4H FVG** (bearish FVG top = buy-side, bullish FVG bottom = sell-side).
   "Fresh" = no 4H candle has traded into the gap yet, so a level can be swept up to and including the 4H candle that first enters it (`InpFvgLiquidity`).
2. **Sweep (Rule 2):** a completed 1H candle trades through a level **and closes back** the other way. A level counts only
   until the first such 1H candle (checked on up to 45,000 1H candles of history). The sweep is remembered for up to 80 1H candles.
3. **4H FVG & inversion (Rule 3):** the **newest bullish 4H FVG** (for a short) that formed **into the sweep** (its middle candle is
   at/before the sweep's 4H candle, starting at most 10 4H candles before it), is complete, and is still **intact** (no 1H close below it
   between its completion and the sweep candle). A 1H candle **closes below it** with **1H displacement** (consecutive bearish closes
   moving >= 1 ATR14) and a **1H MSS** (a close, from the sweep extreme on, below the last confirmed 1H swing low that formed before the extreme).
4. **Entries (Rule 4):** two independent trades per setup (each risks `InpRiskPct`):
   (a) **4H IFVG:** a **sell limit at the 4H IFVG bottom**, valid 48 h; cancelled if a 1H candle opens above the
   sweep extreme first;
   (b) **1H breaker FVG** (`InpBreakerEntry`, magic `InpMagic`+1): the 1H order block of the drop (last up-close 1H candle, looking back 8 candles, before the
   first bearish 1H FVG of the drop) is broken by a 1H **close** below its low; the entry is a limit at the bottom of the first
   bearish 1H FVG whose middle candle is at/after that break candle (within 24 candles). Same stop and target as (a).
   Both can be open together, so `InpOneTradeAtATime` applies per entry kind.
5. **Stop:** above the **50% of the 1H order block of the drop**, no buffer (`InpSwingStopBuffer`, default 0; the trail keeps `InpStopBuffer`). The drop FVG is the first bearish 1H FVG after the sweep extreme
   (its top above the 4H IFVG bottom); the order block is the last up-close 1H candle within 4 candles back from its first candle
   (no order block: the previous completed 1H candle high/low beyond the entry, up to 24 candles back; the stop is fixed when the order is placed).
6. **Target:** the most recent confirmed **1H swing low** (2 candles each side) **before the 4H FVG's middle candle**. If it is not beyond
   the entry, the trade is **skipped** (as in the backtest); `InpUseSwingLowTgt=false` uses a fixed `InpFixedR` instead.
7. **Management:** stop to **breakeven at +1R**, then **trails to each newly confirmed 1H swing** formed after the fill (`InpTrailStructure`). Position size = account balance x risk % / stop distance.

## Inputs
| Input | Default | Meaning |
|---|---|---|
| `InpLiveTrading` | **false** | false = alerts only; true = place real orders |
| `InpRiskPct` | 1.0 | % of balance risked per trade |
| `InpCloseBackSweep` | true | sweep needs a close back through the level |
| `InpPiv4H` | 10 | 4H swing size (10 major, 2 all, 0 off) |
| `InpPivDWM` | 2 | D/W/M swing size |
| `InpFvgLiquidity` | true | fresh 4H FVG far edges as extra liquidity (v1.30) |
| `InpStopBuffer` | 2.0 | points beyond the trailing stop level |
| `InpSwingStopBuffer` | 0.0 | points beyond the initial stop (v1.52) |
| `InpBE_at_R` | 1.0 | breakeven trigger in R (0 = off) |
| `InpBreakerEntry` | true | second entry at a 1H breaker FVG (v1.40; uses magic `InpMagic`+1) |

## Known differences from the tested model
- Swing levels use the broker's own D/W/MN/4H candles (these can differ from the TradingView / MT5-export candles used in the
  backtest, especially the 4H grid), and look at the last ~300 candles per timeframe.
- "Already swept" levels are decided from the 1H history the terminal holds (up to 45,000 candles). If your history is shorter, very
  old levels may be treated as unswept. Make sure the chart has enough 1H, 4H, D, W and MN history.
- Spread, slippage and commission are whatever your broker gives; the backtest used a fixed cost per trade.
- The intraday model is **not** included. Not compiled or tested here: compile in MetaEditor and demo-test first.
