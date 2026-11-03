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
1. **Liquidity:** D / W / M swing highs and lows, 2 candles each side, confirmed after 2 candles.

**Swing model (default, main) – "snapshot rules"** (Python: `swing_snap.py`)
2. **Sweep:** a 1H wick trades above a D/W/M swing high.
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
1. **Liquidity: 4H / D / W / M** – the D/W/M swings plus **4H swing highs / lows with 10 candles each side** (only the
   significant 4H levels; input *4H swings for the intraday model*, 0 = off).
2. **Sweep + leg + FVG:** a wick trades through one of those levels. The leg into the sweep starts at the **last 4H swing low
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
| Intraday liquidity | **4H (10 each side) / D / W / M** |
| Intraday leg start / FVG into sweep / Rule 3 confirmation | Last 4H swing / on / 1H MSS (M1) |
| Stop buffer · Breakeven | 2.0 · +1R |

## Backtest reference – US100 only, 2021-04 → 2026-10
$10,000 start, 1 % risk per trade, compounded, after costs. Python backtest on MT5 4H candles.

| Model | GoatFunded | Pepperstone |
|---|---|---|
| **Swing** (snapshot rules) | 75 trades · win 44 % · PF 1.64 · +12.33R · $10k → $11,255 · max DD 6.4 % | 83 trades · win 48 % · PF 1.75 · +15.96R · $10k → $11,667 · max DD 6.2 % |
| **Intraday** 4H/D/W/M liquidity, 5m touch, prev 1H candle stop | 26 trades · win 50 % · PF 4.48 · +30.02R · $10k → $13,420 · max DD 3.2 % | 26 trades · win 58 % · PF 5.89 · +36.82R · $10k → $14,353 · max DD 3.2 % |
| **Both** (1 % each) | 101 trades · PF 2.52 · +42.35R · $10k → $15,105 · max DD 5.0 % | 109 trades · PF 2.83 · +52.78R · $10k → $16,746 · max DD 6.8 % |

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
