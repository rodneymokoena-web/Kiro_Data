# ICT Sweep > IFVG > MSS – TradingView scripts (US100 forward-test version)

| File | What it is |
|---|---|
| `ict_ifvg_strategy.pine` | **Strategy** – places limit / stop / target orders, Strategy Tester report |
| `ict_ifvg_indicator.pine` | **Indicator** – same logic, draws everything, sends alerts, stats table (no orders) |

Pine Script v5. Uses completed higher-timeframe candles only (no repainting).

## Install
1. TradingView → **Pine Editor** → select all, delete → paste the whole file (normal paste) → **Add to chart**.
2. Open a **5m chart of US100** (e.g. `PEPPERSTONE:NAS100`, `CAPITALCOM:US100`, or your broker's NAS100 / US100 / USTEC).
3. Strategy: **Strategy Tester** tab for the report. Indicator: *Alert → Condition: ICT IFVG → "Any alert() function call"*.

## Rules (identical to the Python backtest)
Short described; long is the mirror image.

**Both models**
1. **Liquidity: 4H / D / W / M** – D/W/M swing highs/lows (2 candles each side, confirmed after 2 candles) plus **4H
   swing highs/lows with 10 candles each side** (only the significant ones), from completed 4H candles. Input *4H swings
   (candles each side)*, 0 = off.

**Swing model (default, main) – "snapshot rules"** (Python: `swing_snap.py`)
2. **Sweep:** a 1H wick trades above a 4H / D / W / M swing high.
3. **4H FVG:** the **last bullish 4H FVG of the leg that swept the level** (middle candle at or before the sweep's 4H
   candle, within 60 4H candles, no 1H close below it before the sweep).
4. **Inversion (4H IFVG):** within 80 1H candles of the sweep, the **first 1H candle that closes below that 4H FVG**,
   with **1H displacement** (≥ 1 bearish candle moving ≥ 1 ATR14) and a **1H MSS** (close below the last 1H swing low
   before the sweep extreme, 2 candles each side).
5. **Entry:** sell limit at the **4H IFVG bottom** (*4H IFVG Touch*; 50% CE optional), valid **48 h** after the 1H
   inversion; cancelled if a candle opens above the sweep extreme before the fill.
6. **Stop:** above the **50% of the 1H order block of the drop** + 2 points. 1H OB = the first candle (the last up-close
   1H candle before the drop) of the first bearish 1H FVG formed by the drop from the sweep extreme. No such FVG → above
   the sweep extreme.
7. **Target:** the **1H swing low** where the leg that built the 4H FVG started (most recent confirmed 1H swing low,
   2 candles each side, before the 4H FVG's middle candle). *Fixed R* optional.

**Intraday model (optional)** (Python: `backtest.py`)
1b. **Also previous-session highs/lows** (Asia / London / NY, New York clock) added to Rule 1, kept only where the
   session extreme is also a swing on 1H or higher. Input *Intraday: previous session highs/lows*.
2. **Sweep + leg + FVG:** a wick trades through one of the Rule 1 levels. The leg into the sweep starts at the **last 4H swing low
   / high before the sweep**. A **4H FVG formed by that leg into the sweep**.
3. **4H inversion (M1):** within 20 4H candles a 4H candle **closes through** that FVG, with 4H displacement (≥ 2
   candles, ≥ 1 ATR14) **and a 1H MSS** by the 4H close. No 4H CISD.
4. **4H IFVG retest** within 48 h (cancelled if price trades beyond the sweep extreme first), then a **1H FVG** of the
   retest leg is inverted with displacement → 1H IFVG.
5. **Entry:** 1H IFVG retest → 5m MSS (or 1H CISD) with displacement → limit at the 5m MSS FVG (**5m Touch** / 50% CE);
   cancelled on a 5m close back through the entry FVG unless re-inverted.
6. **Stop / target:** beyond the **previous completed 1H candle** + 2 points; **3R**.

**Both:** stop to **breakeven at +1R**; the strategy risks 1 % of equity per trade.

## On the chart
- **Entry / stop / target lines** for every pending and open trade: orange = entry, red = stop, green = target, with
  price labels on the right ("LONG PENDING entry …", "SL … (breakeven)" after the stop moves, "TP … (1H swing low, 4.2R)").
  They update every candle (the stop is final at the fill) and turn gray + dotted if the order expires unfilled.
- **Stats table** (top right): model and entry, trades (W / L / BE), win rate, profit factor, total R, average hold,
  stop / target settings and the **active trade** with its entry / SL / TP.
- A 1H IFVG reached through two different 4H setups is traded once.

## Default settings
| Input | Default |
|---|---|
| Trade US100 only | **on** (other symbols: no trades, warning in the table) |
| Model | **Swing** |
| Swing entry / stop / target | **4H IFVG Touch** / **1H OB 50%** / **1H swing low** (valid 48 h) |
| Swing 1H displacement · inversion window · last-FVG lookback | 1 candle · 80 1H candles · 60 4H candles |
| Intraday entry / stop / target | 5m Touch / Previous 1H candle / 3R |
| Liquidity (both models) | **4H (10 each side) / D / W / M** |
| 4H swing size | **10 = major swings** (default); 2 = all swings; 0 = off |
| Intraday also | **Asia/London/NY session highs/lows (1H+ swing)** |
| Intraday leg start / FVG into sweep / Rule 3 confirmation | Last 4H swing / on / 1H MSS (M1) |
| Stop buffer · Breakeven | 2.0 · +1R |

## Backtest reference – US100 only, 2021-04 → 2026-10
$10,000 start, 1 % risk per trade, compounded, after costs. Python backtest on MT5 4H candles.

| Model | GoatFunded | Pepperstone |
|---|---|---|
| **Swing** (snapshot rules, 4H/D/W/M) | 104 trades · win 45 % · PF 1.39 · +11.52R · $10k → $11,155 · max DD 7.9 % | 111 trades · win 51 % · PF 1.61 · +18.04R · $10k → $11,903 · max DD 8.0 % |
| **Intraday** 4H/D/W/M + session liquidity, 5m touch | 73 trades · win 25 % · PF 1.40 · +15.28R · $10k → $11,537 · max DD 7.7 % | 76 trades · win 34 % · PF 2.23 · +42.45R · $10k → $15,092 · max DD 7.4 % |
| **Both** (1 % each) | 177 trades · PF 1.40 · +26.80R · $10k → $12,870 · max DD 14.3 % | 187 trades · PF 1.95 · +60.49R · $10k → $17,964 · max DD 10.5 % |

2021-2023 (never used for tuning) / 2024-2026: swing +3.13R / +9.20R (GoatFunded), +6.49R / +9.47R (Pepperstone);
intraday +16.62R / +13.41R (GoatFunded), +24.38R / +12.44R (Pepperstone). About 14 swing and 5 intraday trades per year.

Monthly view (each month starts at $10,000, 1 % risk, both models): 43-45 % of months profitable, ~30 % without
trades, average +$65 / +$80 per month (GoatFunded / Pepperstone), worst month about -$300 (-3 %), best about +$1,150.

**4H candles differ between MT5 and TradingView** (TradingView starts US100 4H candles at the 18:00 New York session
open, MT5 one hour later), so some 4H FVGs – and trades – differ. On TradingView's 4H candles the Python swing model
made +11.3R (GoatFunded) / +11.6R (Pepperstone) over the same period.

TradingView results will differ somewhat: chart history depends on your plan, D/W/4H candles follow the symbol's
session, orders are placed at the close of the candle on which the signal is known, and the strategy cannot hold a long
and a short at the same time.
