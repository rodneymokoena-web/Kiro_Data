# ICT US100 strategy – Python backtest

Python backtest of the ICT strategy traded with the TradingView scripts in `../tradingview/`
(D/W/M liquidity sweep → 4H FVG inversion → entry), US100 only. Price data is **not** in this folder (about 15 GB);
rebuild it with the scripts below.

## Setup
```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
export MPLCONFIGDIR=/tmp/mpl          # matplotlib cache (charts)
```

## Data
| Source (`DATA_SOURCE`) | Folder | How to build |
|---|---|---|
| `goat`, `pepperstone` (2024-01 → 2026-10) | `data/goat/`, `data/pepperstone/` | MT5 M1 exports (tab-separated, server time NY+7): `.venv/bin/python fetch_goat.py --source goat` (see the script header for the input file names) |
| `goat_oos`, `pepperstone_oos` (2021-01 → 2023-12, never used for tuning) | `data/goat_oos/`, `data/pepperstone_oos/` | same, `--source goat_oos` / `pepperstone_oos` |
| `exness` (2020-07 → 2026-10, also tick data) | `data/exness/`, `data/exness_ticks/` | `.venv/bin/python fetch_exness_ticks.py 2020-07 2026-10` then `.venv/bin/python build_exness_bars.py` (free public archive; `EXNESS_SYMBOL=XAUUSD` for gold) |

Each folder holds `US100_{1m,5m,15m,1h}.csv` and `costs.json` (cost per trade in price units; included here).

## Run
```bash
# all US100 results (4 broker data sets, both models) -> output/us100_summary_2021_2026.csv, us100_*_levels.csv, ...
.venv/bin/python make_us100_results.py

# one data set, one model
DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python backtest.py        # intraday
DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python swing_snap.py      # swing
DATA_SOURCE=pepperstone_oos TEST_START=2021-04-01 ...                              # 2021-2023 out of sample

# Exness: signals on Exness candles, fills / exits replayed on Exness ticks
DATA_SOURCE=exness TEST_START=2021-04-01 .venv/bin/python exness_backtest.py
# broker trades replayed on Exness ticks
.venv/bin/python tick_backtest.py

# TradingView scripts: edit pine/core.pine, then build + syntax-check both scripts (~3 min)
.venv/bin/python pine/build.py
```
Other settings: `TRADE_SYMBOLS` (default `US100`), `H4_GRID` (`mt5` default, `tradingview` = 4H candles from the
18:00 New York session open like TradingView).

## Current rules (defaults)
**Swing model** – `swing_snap.py` ("snapshot rules", short described, long mirrored)
1. A 1H wick trades above a **D/W/M swing high** (2 candles each side).
2. The **last bullish 4H FVG of the leg** that swept it (within 60 4H candles, no 1H close below it before the sweep).
3. The **first 1H close below it** within 80 1H candles, with 1H displacement (≥ 1 candle, ≥ 1 ATR) + 1H MSS.
4. **Entry:** sell limit at the 4H IFVG bottom, valid 48 h; cancelled if a candle opens above the sweep extreme.
5. **Stop:** above the 50% of the 1H order block of the drop (+ buffer). **Target:** the 1H swing low where the leg
   that built the 4H FVG started. Breakeven at +1R.

**Intraday model** – `backtest.py` (rules 1-7)
1. Liquidity: **D/W/M swings + 4H swings with 10 candles each side**.
2. Sweep → 4H FVG of the leg from the last 4H swing, formed into the sweep (`ifvg.py`).
3. 4H close through it with 4H displacement (≥ 2 candles, ≥ 1 ATR) + **1H MSS** (`ifvg_1h.CONFIRM_4H = "1H MSS"`).
4. 4H IFVG retest within 48 h (cancelled beyond the sweep extreme) → 1H IFVG with displacement (`ifvg_1h.py`).
5. 1H IFVG retest → 5m MSS (or 1H CISD) with displacement → limit at the 5m MSS FVG near edge (`entry_ltf.py`).
6. Stop: previous completed 1H candle beyond the entry (+ buffer). Target 3R. Breakeven at +1R.

## Main modules
| File | What |
|---|---|
| `swings.py` | data loading, D/W/M/4H candles, swing levels (rule 1), break times |
| `ifvg.py` | FVGs, sweep → FVG → inversion (4H) |
| `structure.py` | displacement, CISD, MSS |
| `ifvg_1h.py` | 4H setups (rules 2-4) and the 1H IFVG (rule 5) |
| `setups_v3.py` | 4H FVG inverted on 1H (used by the swing model) |
| `swing_snap.py` | swing model (entry, 1H OB stop, 1H swing-low target) |
| `entry_ltf.py`, `backtest.py` | intraday entry (rule 6) and trade simulation (rule 7) |
| `stops_ext.py` | alternative stops (order blocks, FVGs) |
| `make_us100_results.py` | regenerates every US100 result file |
| `fetch_exness_ticks.py`, `build_exness_bars.py`, `tick_backtest.py`, `exness_backtest.py` | Exness tick data and tick replay |
| `*_experiments.py` | the rule tests run during development (results in `output/`) |
| `swing.py` | previous swing model (1H IFVG entry), kept as a reference |

## Results (output/)
- `us100_summary_2021_2026.csv` – both models, both brokers, 2021-26 / unseen / tuned, capital and drawdown
- `us100_{broker}_{model}_levels.csv` – every trade with entry, stop, target, exit and R
- `us100_capital_by_year.csv`, `us100_monthly_reset*.csv` – capital per year, per month ($10k each month)
- `exness_*.csv` – Exness backtest with tick execution (US100 and `_xauusd`)
- `tick_trades.csv`, `tick_summary.csv` – broker trades replayed on Exness ticks
- `*_summary.csv` – results of each rule test
