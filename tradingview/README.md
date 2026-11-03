# ICT Sweep > IFVG > MSS – TradingView scripts (US100 forward-test version)

| File | What it is |
|---|---|
| `ict_ifvg_strategy.pine` | **Strategy** – places limit / stop / target orders, Strategy Tester report |
| `ict_ifvg_indicator.pine` | **Indicator** – same logic, draws everything, sends alerts, stats table (no orders) |
| `core.pine` | shared source of both scripts – edit this, then run `.venv/bin/python pine/build.py` |

Pine Script v5. Uses completed higher-timeframe candles only (no repainting).

## Install
1. TradingView → **Pine Editor** → select all, delete → paste the whole file (normal paste) → **Add to chart**.
2. Open a **5m chart of US100** (e.g. `PEPPERSTONE:NAS100`, `CAPITALCOM:US100`, or your broker's NAS100 / US100 / USTEC).
3. Strategy: **Strategy Tester** tab for the report. Indicator: *Alert → Condition: ICT IFVG → "Any alert() function call"*.

## Rules (identical to the Python backtest)
1. **Liquidity:** D / W / M swing highs and lows, 2 candles each side, confirmed after 2 candles.
2. **Sweep + leg + FVG:** a wick trades through a D/W/M level. The leg into the sweep starts at the **last 4H swing
   low / high before the sweep** (2 candles each side). A **4H FVG formed by that leg into the sweep** (middle candle at
   or before the sweep candle).
3. **4H inversion (Rule 3 "M1"):** within 20 4H candles a 4H candle **closes through** that FVG, with 4H displacement
   (≥ 2 candles, ≥ 1 ATR14) **and a 1H MSS**: a 1H close through the last 1H swing low (short) / high (long) before
   the sweep extreme, by the close of the 4H inversion candle. **No 4H CISD.** (Input *Rule 3 confirmation* can switch
   back to the previous "4H CISD or MSS".)
   - **Optional, swing only – Rule 3 "1H wick + close (M6)"** (input *Rule 3: 4H FVG inversion*, off by default):
     the sweep is timed on 1H; the **last 4H FVG of the sweeping leg** (middle candle at or before the sweep's 4H
     candle, within 60 4H candles, no 1H close through it before the sweep) is inverted by the **first 1H candle whose
     wick trades through it**, and that candle must **close through it**, with 1H displacement and a **1H MSS** = a
     close through the most recent confirmed 1H swing low / high, formed before or after the sweep. No 4H CISD.
     Within 80 1H candles of the sweep. Intraday always uses M1.
4. **4H IFVG retest** within 48 h, then a **1H FVG** of the retest leg is inverted with displacement → 1H IFVG signal.
5. **Entry:**
   - **Swing (default, main):** limit at the 1H IFVG – **1H Touch** (default) or 1H 50% CE – valid 24 h.
   - **Intraday (optional):** 1H IFVG retest → 5m MSS (or 1H CISD) with displacement → limit at the 5m MSS FVG –
     **5m Touch** (default) or 5m 50% CE; cancelled on a 5m close back through the entry FVG unless re-inverted.
6. **Risk:**
   - **Swing stop: 4H order block** – above the high of the last up-close 4H candle before the 4H displacement that
     inverted the FVG (short; long: below the low of the last down-close candle). M6 option: the last up-close
     completed 4H candle of the sweeping leg.
   - **Intraday stop:** beyond the **previous completed 1H candle** high / low beyond the entry.
   - Both: + 2 point buffer, **target 3R**, **stop to breakeven at +1R**; strategy risks 1 % of equity per trade.

## On the chart
- **Entry / stop / target lines** for every pending and open trade: orange = entry, red = stop, green = target, with
  price labels on the right ("LONG PENDING entry …", "SL … (breakeven)" after the stop moves, "TP … (3R)").
  They update every candle (the stop is final at the fill) and turn gray + dotted if the order expires unfilled.
- **Stats table** (top right): model and entry, trades (W / L / BE), win rate, profit factor, total R, average hold,
  stop / target settings and the **active trade** with its entry / SL / TP.
- A 1H IFVG reached through two different 4H setups is traded once.

## Default settings
| Input | Default |
|---|---|
| Trade US100 only | **on** (other symbols: no trades, warning in the table) |
| Model | **Swing (1H entry)** |
| Swing entry filter / stop | **1H Touch** / **4H order block** (options: 4H sweep extreme, previous 4H candle) |
| Intraday entry filter / stop | 5m Touch / Previous 1H candle |
| Leg start / FVG into sweep | **Last 4H swing** / **on** |
| Rule 3 confirmation | **1H MSS (M1)** – previous: 4H CISD or MSS |
| Rule 3: 4H FVG inversion | **4H close (M1)** – optional *1H wick + close (M6)* for the swing model |
| Stop buffer · Target · Breakeven | 2.0 · 3R · +1R |

## Backtest reference – US100 only, 2021-04 → 2026-10
| Model | GoatFunded | Pepperstone |
|---|---|---|
| **Swing** 1H touch, 4H order block stop | 28 trades · win 39 % · PF 4.08 · +24.87R · $10k → $12,757 · max DD 2.0 % | 30 trades · win 40 % · PF 3.55 · +25.82R · $10k → $12,871 · max DD 3.0 % |
| **Intraday** 5m touch, prev 1H candle stop | 21 trades · win 48 % · PF 3.51 · +21.27R · $10k → $12,311 · max DD 3.2 % | 22 trades · win 55 % · PF 4.75 · +28.04R · $10k → $13,163 · max DD 3.2 % |
| **Both** (1 % each) | 49 trades · PF 3.79 · +46.14R · $10k → $15,705 · max DD 3.1 % | 52 trades · PF 4.06 · +53.86R · $10k → $16,943 · max DD 5.1 % |

Rules as in these scripts (Rule 3 M1, leg from the last 4H swing, FVG formed into the sweep). 2021-2023 alone:
swing +12.94R / +11.87R, intraday +10.76R / +18.55R (GoatFunded / Pepperstone). Capital: $10,000 start, 1 % risk
per trade, compounded, after costs.

Optional swing Rule 3 **M6** (Python, with its "last 4H FVG of any sweeping leg" Rule 2), 2021-04 → 2026-10:
GoatFunded 10 trades · PF 17.7 · +16.97R · max DD 1.0 %; Pepperstone 16 trades · PF 4.4 · +13.89R · max DD 2.0 %
(4H order block stop)
(small sample – forward-test it next to the default).

2021-2023 was never used for tuning (out of sample). About 5 swing and 4 intraday trades per year.
Both models trade the same setups – if you run both on one account, use 0.5 % risk per model.

TradingView results will differ somewhat: chart history depends on your plan, D/W/4H candles follow the symbol's
session, orders are placed at the close of the candle on which the signal is known, and the strategy cannot hold a long
and a short at the same time.
