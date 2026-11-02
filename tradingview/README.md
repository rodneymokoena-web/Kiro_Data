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
3. **4H inversion:** within 20 4H candles a 4H candle **closes through** that FVG, with displacement (≥ 2 candles,
   ≥ 1 ATR14) **and** CISD or MSS.
4. **4H IFVG retest** within 48 h, then a **1H FVG** of the retest leg is inverted with displacement → 1H IFVG signal.
5. **Entry:**
   - **Swing (default, main):** limit at the 1H IFVG – **1H Touch** (default) or 1H 50% CE – valid 24 h.
   - **Intraday (optional):** 1H IFVG retest → 5m MSS (or 1H CISD) with displacement → limit at the 5m MSS FVG –
     **5m Touch** (default) or 5m 50% CE; cancelled on a 5m close back through the entry FVG unless re-inverted.
6. **Risk:** swing stop beyond the **4H sweep extreme**, intraday stop beyond the **previous completed 1H candle**
   (+ 2 point buffer); **target 3R**; **stop to breakeven at +1R**; strategy risks 1 % of equity per trade.

## Default settings
| Input | Default |
|---|---|
| Trade US100 only | **on** (other symbols: no trades, warning in the table) |
| Model | **Swing (1H entry)** |
| Swing entry filter / stop | **1H Touch** / **4H sweep extreme** |
| Intraday entry filter / stop | 5m Touch / Previous 1H candle |
| Leg start / FVG into sweep | **Last 4H swing** / **on** |
| Stop buffer · Target · Breakeven | 2.0 · 3R · +1R |

## Backtest reference – US100 only, 2021-04 → 2026-10
| Model | GoatFunded | Pepperstone |
|---|---|---|
| **Swing** 1H touch, 4H extreme stop | 24 trades · PF 3.34 · +18.90R · max DD 2.0 % | 24 trades · PF 2.97 · +17.88R · max DD 2.0 % |
| **Intraday** 5m touch, prev 1H candle stop | 17 trades · PF 3.25 · +14.44R · max DD 2.2 % | 17 trades · PF 4.93 · +21.29R · max DD 2.1 % |

2021-2023 was never used for tuning (out of sample). About 4 swing and 3 intraday trades per year.
Both models trade the same setups – if you run both on one account, use 0.5 % risk per model.

TradingView results will differ somewhat: chart history depends on your plan, D/W/4H candles follow the symbol's
session, orders are placed at the close of the candle on which the signal is known, and the strategy cannot hold a long
and a short at the same time.
