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
2. **Sweep (Rule 2):** a completed 1H candle trades through a level **and closes back** the other way.
   The sweep is remembered for up to 80 1H candles.
3. **4H FVG & inversion (Rule 3):** the last bullish 4H FVG (within 60 4H candles, still intact) is **closed below by a
   1H candle** that also has **1H displacement** (>= 1 ATR) and a **1H MSS**.
4. **Entry (Rule 4):** a **sell limit at the 4H IFVG bottom**, valid 48 h; cancelled if a 1H candle opens above the
   sweep extreme first.
5. **Stop:** above the **50% of the 1H order block of the drop** + buffer (fallback: beyond the sweep extreme).
6. **Target:** the nearest confirmed **1H swing low** beyond the entry (fallback: fixed R).
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
| `InpStopBuffer` | 2.0 | points beyond the stop level |
| `InpBE_at_R` | 1.0 | breakeven trigger in R (0 = off) |

## Known differences from the tested model
- Sweep -> inversion timing is tracked per 1H candle, but the "last 4H FVG of the leg" is chosen as the most recent
  intact one, not anchored to the sweep candle exactly.
- The **1H swing-low target** is the nearest confirmed 1H swing beyond the entry, not anchored to the 4H FVG's
  formation candle.
- Swing levels are rebuilt from the last ~300 candles per timeframe and use the broker's own D/W/MN candles (these can
  differ from the TradingView / MT5-export candles used in the backtest, especially the 4H grid).
- Spread, slippage and commission are whatever your broker gives; the backtest used a fixed cost per trade.
- The session-liquidity layer and the intraday model are **not** included.

Expect to tune and verify it against the TradingView indicator before relying on it.
