# ICT Sweep > IFVG > MSS – TradingView scripts

| File | What it is |
|---|---|
| `ict_ifvg_strategy.pine` | **Strategy** – places limit / stop / target orders, Strategy Tester report |
| `ict_ifvg_indicator.pine` | **Indicator** – same logic, draws everything, sends alerts, stats table (no orders) |
| `core.pine` | shared source of both scripts – edit this, then run `.venv/bin/python pine/build.py` |

Pine Script v5. Both scripts use completed higher-timeframe candles only (no repainting).

## Install
1. TradingView → **Pine Editor** → select all, delete → paste the whole file (normal paste) → **Add to chart**.
2. Use a **5m chart** of your symbol (e.g. `PEPPERSTONE:NAS100`, `PEPPERSTONE:XAUUSD`, or your broker's).
3. Strategy: open the **Strategy Tester** tab for the report. Indicator: create alerts with
   *Alert → Condition: ICT IFVG → "Any alert() function call"*.

## Settings
**Model**
| Input | Options | Notes |
|---|---|---|
| Model | **Intraday (5m entry)** / **Swing (1H entry)** | |
| Swing entry filter | **1H Touch** / **1H 50% CE** | limit at the 1H IFVG near edge / midpoint |
| Swing stop | **4H sweep extreme** (recommended) / Previous 4H candle | |
| Swing order valid | 24 h | after the 1H signal |

**Rule 6 – intraday entry**
| Input | Options | Notes |
|---|---|---|
| Intraday entry filter | **5m Touch** / **5m 50% CE** | limit at the 5m MSS FVG near edge / midpoint |
| windows | retest 24 h, trigger 12 h, order valid 12 h | |
| 5m close-back-through cancel | on | order cancelled on a 5m close back through the entry FVG unless the next 5m candle re-inverts it |

**Rule 7 – risk**
| Input | Default | Notes |
|---|---|---|
| Intraday stop | **Previous 1H candle** / 4H sweep extreme | |
| Stop buffer | 2.0 | use ~2 for US100, **~0.5 for gold** |
| Target | 3R | |
| Breakeven | on, at +1R | |
| Risk per trade (strategy) | 1 % of equity | quantity = risk / (stop distance × point value), rounded to the quantity step |

## Backtest reference (Python, 2024-01-01 → 2026-10-30)
| Model / settings | GoatFunded | Pepperstone |
|---|---|---|
| Intraday, 5m Touch, prev 1H candle stop | PF 2.12, +10.97R | PF 2.16, +11.22R |
| Intraday, 5m 50% CE, prev 1H candle stop | PF 2.15, +12.64R | PF 2.71, +15.05R |
| Swing, 1H Touch or CE, 4H sweep extreme stop | PF 1.67, +10.82R | PF 1.79, +11.88R |

TradingView results will differ somewhat: chart history is limited by your plan, D/W/4H candles follow the
symbol's session, orders are placed at the close of the candle on which the signal is known (swing: within 5
minutes on a 5m chart), and the strategy cannot hold a long and a short at the same time.
