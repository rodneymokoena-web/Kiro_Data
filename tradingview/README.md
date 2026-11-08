# ICT Sweep > IFVG > MSS – TradingView scripts (US100 forward-test version)

The two models are separate scripts (one model per script):

| File | What it is |
|---|---|
| `ict_swing_indicator.pine` | **Swing indicator** – draws the swing setups, entries, stop / target, sends alerts, stats table (no orders) |
| `ict_swing_strategy.pine` | **Swing strategy** – same swing logic, places the orders, Strategy Tester report |
| `ict_intraday_indicator.pine` | **Intraday indicator** – the intraday model (5m chart), alerts, stats table (no orders) |
| `ict_intraday_strategy.pine` | **Intraday strategy** – same intraday logic, places the orders, Strategy Tester report |

Pine Script v5. Uses completed higher-timeframe candles only (no repainting).

## Install
1. TradingView → **Pine Editor** → select all, delete → paste the whole file (normal paste) → **Add to chart**.
2. Open a **5m chart of US100** (swing also works on 1m–1H; intraday needs 5m) (e.g. `PEPPERSTONE:NAS100`, `CAPITALCOM:US100`, or your broker's NAS100 / US100 / USTEC).
3. Strategy: **Strategy Tester** tab for the report. Indicator: *Alert → Condition: ICT Swing* (or *ICT Intraday*) *→ "Any alert() function call"*. Add both indicators to the chart to watch both models.

## Rules (identical to the Python backtest)
Short described; long is the mirror image.

**Both models**
1. **Liquidity: 4H / D / W / M** – D/W/M swing highs/lows (2 candles each side, confirmed after 2 candles) plus **4H
   swing highs/lows with 10 candles each side** (only the significant ones), from completed 4H candles. Input *4H swings
   (candles each side)*, 0 = off. **Also the far edge of every fresh 4H FVG** (bearish FVG top = buy-side level, bullish
   FVG bottom = sell-side level). *Fresh* = price has not traded into the gap yet, so the level can be swept up to and
   including the 4H candle that first enters the FVG. Input *4H FVG far edge as liquidity* (on by default).

**Swing model (default, main) – "snapshot rules"** (Python: `swing_snap.py`)
2. **Sweep:** a 1H candle trades above a 4H / D / W / M swing high **and closes back below it** (a rejection sweep; input *Swing: sweep must close back through the level*).
3. **4H FVG:** the **last bullish 4H FVG of the leg that swept the level** (middle candle at or before the sweep's 4H
   candle, within 10 4H candles, no 1H close below it before the sweep).
4. **Inversion (4H IFVG):** within 80 1H candles of the sweep, the **first 1H candle that closes below that 4H FVG**,
   with **1H displacement** (≥ 1 bearish candle moving ≥ 1 ATR14) and a **1H MSS** (close below the last 1H swing low
   before the sweep extreme, 2 candles each side).
5. **Entries (two independent trades per setup):** (a) sell limit at the **4H IFVG bottom** (*4H IFVG Touch*; 50% CE optional), valid **48 h** after the 1H
   inversion; cancelled if a candle opens above the sweep extreme before the fill. (b) **second entry at a 1H breaker FVG**
   (input *Swing: second entry at a 1H breaker FVG*, on by default): the 1H order block of the drop (last up-close 1H candle, looking back 8 candles,
   before the first bearish 1H FVG of the drop) is broken by a 1H **close** below its low; sell limit at the bottom of the
   first bearish 1H FVG whose middle candle is at/after the break candle (within 24 candles). Long = mirror. Same stop and
   target; both trades can be open together (the strategy uses pyramiding 5).
6. **Stop:** above the **50% of the 1H order block of the drop**, no buffer (input *Swing: buffer beyond the initial stop*, default 0; the trailing stop keeps the 2-point buffer). 1H OB = the first candle (the last up-close
   1H candle before the drop) of the first bearish 1H FVG formed by the drop from the sweep extreme. No order block → the **previous completed 1H candle high** (low for a long) beyond the entry.
7. **Target:** the **1H swing low** where the leg that built the 4H FVG started (most recent confirmed 1H swing low,
   2 candles each side, before the 4H FVG's middle candle). *Fixed R* optional.

**Intraday model (optional)** (Python: `backtest.py`)
0. **Intraday sweep (5m chart):** a Rule 1 level is swept when (A) a **5m candle wicks through it and closes back** (high level: high above, close below), or
   (B) **1 or 2 5m candles close beyond it** and are immediately followed by **two strong displacement 5m candles** in the reversal direction (together >= 1 ATR14),
   the second closing beyond the low (high) of the last sweeping candle. The first sweep event uses the level up (input *Intraday: judge the sweep on 5m candles*; off = a 4H wick). The rest of the chain is unchanged.
1a. **Intraday model only, also:** **1H swings** (same size as the 4H swings, 10 candles each side) and the far edge of every **fresh 1H FVG**
   (inputs *Intraday: 1H swings*, *Intraday: fresh 1H FVG far edges*; both are swept by 4H wicks).
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

**Both:** stop to **breakeven at +1R** (swing model then also trails to new 1H swings); the strategy risks 1 % of equity per trade.

## Alerts (entry alerts)
Add the **indicator** to a chart (5m recommended), then *Alert -> Condition: ICT IFVG*:
- **"Any alert() function call"** - one alert that sends every message with the details (symbol, long/short, entry type, entry / SL / TP):
  - `... ENTRY ORDER (4H IFVG | 1H breaker FVG) limit <price> | SL <price> | TP <price>` - when a limit order is placed;
  - `... ENTRY FILLED (<entry type>) @ <price> | SL <price> | TP <price> | risk <pts>` - when it fills;
  - `... stop moved to breakeven ...` and `... trade closed: <target|stop|breakeven|trailed> <R>`;
  - plus the setup messages (4H / swing setup, 1H IFVG signal, 1H breaker FVG entry found).
- **Ready-made conditions** (pick them in the Condition list): *Long entry order placed*, *Short entry order placed*, *Long entry filled*,
  *Short entry filled*, *Any entry filled*, *Trade closed*. These carry a fixed text; use "Any alert() function call" if you want the prices.
Set the alert to **Once per bar close**. Alerts only fire on live (real-time) bars; the strategy script sends the same `alert()` messages and its
orders can also be alerted from the Strategy Tester (*Order fills only*). Alerts work on a 5m chart for both models.

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
| Swing entry / stop / target | **4H IFVG Touch + 1H breaker FVG (second entry)** / **1H OB 50%** / **1H swing low** (valid 48 h) |
| Swing 1H displacement · inversion window · last-FVG lookback | 1 candle · 80 1H candles · 10 4H candles |
| Intraday entry / stop / target | 5m Touch / Previous 1H candle / 3R |
| Liquidity (both models) | **4H (10 each side) / D / W / M + fresh 4H FVG far edges** |
| 4H swing size | **10 = major swings** (default); 2 = all swings; 0 = off |
| Swing sweep | **close back through the level** (rejection); intraday uses a wick |
| Intraday also | **Asia/London/NY session highs/lows (1H+ swing)** |
| Intraday leg start / FVG into sweep / Rule 3 confirmation | Last 4H swing / on / 1H MSS (M1) |
| Stop buffer · Breakeven | 2.0 · +1R |

## Backtest reference – US100 only, 2021-04 → 2026-10
$10,000 start, 1 % risk per trade, compounded, after costs. Python backtest on MT5 4H candles.

| Model | GoatFunded | Pepperstone |
|---|---|---|
| **Swing** (snapshot rules, 4H/D/W/M + fresh 4H FVG edges, close-back sweep, trailing stop) | 253 trades · win 46 % · PF 1.68 · +64.52R · $10k → $18,462 · max DD 10.2 % | 277 trades · win 47 % · PF 1.84 · +82.05R · $10k → $21,715 · max DD 6.3 % |
| **Intraday** D/W/M + 4H/1H swings + 4H/1H fresh FVG edges + session liquidity, 5m touch | 78 trades · win 23 % · PF 1.29 · +12.05R · $10k → $11,169 · max DD 10.6 % | 85 trades · win 33 % · PF 2.14 · +44.04R · $10k → $15,318 · max DD 7.6 % |
| **Both** (1 % each) | 331 trades · PF 1.56 · +76.57R · $10k → $20,620 · max DD 12.3 % | 362 trades · PF 1.93 · +126.09R · $10k → $33,262 · max DD 12.7 % |

2021-2023 (never used for tuning) / 2024-2026: swing +36.45R / +25.49R (GoatFunded), +23.73R / +57.87R (Pepperstone);
intraday +18.07R / -2.83R (GoatFunded), +27.11R / +18.33R (Pepperstone). About 55 swing and 13 intraday trades per year.

Adding the fresh 4H FVG far edges lifted the swing model from 122 / 132 trades (+24.3R / +26.0R) to 162 / 175 trades (+35.6R / +43.8R, with the 10-candle FVG lookback) and left the intraday model almost unchanged. The second entry at the 1H breaker FVG then took the swing model to 253 / 277 trades (+62.0R / +81.6R) at about twice the drawdown (11.6 % / 6.4 %). The monthly statistics of earlier versions were not
re-computed.

**4H candles differ between MT5 and TradingView** (TradingView starts US100 4H candles at the 18:00 New York session
open, MT5 one hour later), so some 4H FVGs – and trades – differ. On TradingView's 4H candles the Python swing model
produces fewer trades and less R than on the MT5 grid (not re-measured for the FVG-edge rule).

TradingView results will differ somewhat: chart history depends on your plan, D/W/4H candles follow the symbol's
session, orders are placed at the close of the candle on which the signal is known, and the strategy cannot hold a long
and a short at the same time.
