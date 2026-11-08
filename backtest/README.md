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
2. The **last bullish 4H FVG of the leg** that swept it (within 10 4H candles, no 1H close below it before the sweep).
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

## Update: fresh 4H FVG far edge as Rule 1 liquidity (default on)
Both models also treat the **far edge of every 4H FVG** as a sweepable level (bearish FVG top = buy-side, bullish FVG
bottom = sell-side), but only while the FVG is **fresh** (price has not traded into the gap yet; the 4H candle that first
enters it can still sweep it). Switches: `FVG_LIQ=0|1` (`ifvg.FVG_LIQ`), `FVG_LIQ_MODE=all|intact|fresh`
(`swings.fvg_far_edge_levels`). Tests: `fvgliq_experiments.py`, `output/fvgliq_summary*.csv`.
2021-2026, $10k, 1% risk (GoatFunded / Pepperstone): swing 122 -> 225 / 132 -> 240 trades, +24.3R -> +34.0R / +26.0R -> +44.5R,
max DD 4.8% -> 7.5% / 7.1% -> 5.3%; intraday almost unchanged; both models 299 / 317 trades, +49.2R / +90.0R, max DD 10.2% / 9.6%.
Also tested and **not adopted**: a Rule 1 bias filter (`bias.py`, `bias_experiments.py`, `output/bias_summary.csv`) - it
removed about three quarters of the swing trades and most of the profit.

## Update: swing Rule 2 lookback 60 -> 10 4H candles (default)
The last 4H FVG of the sweeping leg must be within 10 4H candles of the sweep (`LEG_LOOKBACK_4H`, env `LEG_LB`).
2021-2026 swing (GoatFunded / Pepperstone): 225 / 240 -> 162 / 175 trades, PF 1.52 / 1.68 -> 1.84 / 2.05, R +34.0 / +44.5 -> +35.6 / +43.8,
max DD 7.5% / 5.3% -> 5.6% / 3.5%. Both models: +50.8R / +89.3R, $16,318 / $23,863. Results: `output/lb_summary.csv`.

## Update: swing model takes BOTH entries (4H IFVG + 1H breaker FVG) - default
Each swing setup now trades two independent entries (1% risk each, same stop and target):
1. limit at the 4H IFVG near edge (as before), and
2. limit at a **1H breaker FVG**: the 1H order block of the drop (last up-close 1H candle before the first bearish 1H FVG of the
   drop from the sweep extreme) is broken by a 1H **close** below its low; entry = bottom of the first bearish 1H FVG whose middle
   candle is at/after the break candle (within 24 candles). Long = mirror. Switches: `ENTRY_KIND=both|4h|breaker|either`,
   `BREAKER_BREAK=close|wick`, `BREAKER_FVG=first|any` (`swing_snap.py`). Tests: `entrykind_experiments.py`,
   `output/entrykind_summary.csv`, `output/entrykind_both_summary.csv`; monthly view: `output/monthly_both_entries.csv`.
2021-2026, $10k, 1% risk (GoatFunded / Pepperstone): swing 162 / 175 -> 252 / 276 trades, +35.6R / +43.8R -> +61.3R / +81.0R, PF 1.84 / 2.05 -> 1.69 / 1.85,
max DD 5.6% / 3.5% -> 11.6% / 6.4%. Both models: 326 / 353 trades, +76.5R / +126.4R, $20,730 / $33,533, max DD 15.4% / 10.6%.
The gain mostly comes from taking more risk (two trades per setup, often open together); return per unit of drawdown is about unchanged.

## Update: breaker order block looks back 8 candles (was 4) - default
`BREAKER_OB_LB = 8` in `swing_snap.py` (env `BREAKER_OB_LB`): the order block is the last up-close 1H candle within 8 candles before the first
bearish 1H FVG of the drop. Other breaker definitions tested and NOT adopted (entry at the block, OB before the sweep, break must take a 1H
swing, lookback 2, break window 24/96): `output/breaker_variants_summary.csv`; their switches (`BREAKER_ENTRY`, `BREAKER_OB_BEFORE`,
`BREAKER_SWING_BREAK`, `BREAKER_BREAK_BARS`) stay off by default.
2021-2026 swing (GoatFunded / Pepperstone): 253 / 277 trades, PF 1.70 / 1.86, +62.0R / +81.6R, max DD 11.0% / 6.1%. Both models: 327 / 354 trades,
+77.2R / +127.0R, $20,872 / $33,753, max DD 14.8% / 10.6%.

## Update: swing stop without an order block = previous 1H candle high/low (default)
`OB_FALLBACK = "prev 1H candle"` in `swing_snap.py` (env `OB_FALLBACK`, `sweep extreme` restores the old fallback): when the drop has no 1H order block,
the stop is the previous completed 1H candle high (short) / low (long) beyond the entry (up to 24 candles back), plus the 2-point buffer.
It applies to about 27-32 trades per broker. Test: `obfb_experiments.py`, `output/ob_fallback_summary.csv`.
2021-2026 swing (GoatFunded / Pepperstone): 253 / 277 trades, PF 1.70 / 1.86 -> 1.66 / 1.79, +62.0R / +81.6R -> +60.7R / +77.4R, max DD 11.0% / 6.1% -> 10.3% / 6.3%.
Both models: 327 / 354 trades, +75.9R / +122.8R, $20,577 / $32,332, max DD 12.2% / 10.7%.

## Update: swing initial stop has no buffer (default)
`SWING_STOP_BUF = 0` in `swing_snap.py` (env `SWING_BUF`): the stop is exactly at 50% of the 1H order block (or the previous 1H candle high/low when there is
none). The trailing stop keeps its 2-point buffer (`SL_BUFFER`); the intraday model is unchanged. Test: `buf_experiments.py`.
2021-2026 swing (GoatFunded / Pepperstone): PF 1.66 / 1.79 -> 1.68 / 1.84, +60.7R / +77.4R -> +64.5R / +82.1R, max DD 10.3% / 6.3% -> 10.2% / 6.3%.
Both models: 327 / 354 trades, +79.8R / +127.5R, $21,291 / $33,750, max DD 11.9% / 10.8%.

## Update: intraday Rule 1 also uses 1H swings and fresh 1H FVG far edges (default)
Intraday liquidity is now D/W/M swings (2 candles each side), **4H and 1H swings (10 each side)**, fresh **4H and 1H** FVG far edges, and the previous
Asia / London / NY highs and lows (kept only if also a 1H+ swing, valid 7 days). Switches: `INTRADAY_LIQ_TFS` (`backtest.py`, default `M,W,D,4H,1H`) and
`FVG_LIQ_1H` (`ifvg_1h.py`). Swing model unchanged. Test: `intliq_experiments.py`.
2021-2026 intraday (GoatFunded / Pepperstone): 74 / 77 -> 76 / 80 trades, PF 1.40 / 2.32 -> 1.32 / 2.13, +15.2R / +45.4R -> +13.1R / +42.4R,
max DD 7.7% / 7.4% -> 9.6% / 7.4% (1H swings and 1H FVG edges each add about one trade and slightly lower the profit factor).
Both models: 329 / 357 trades, +77.7R / +124.4R, $20,843 / $32,724, max DD 11.9% / 11.7%.

## Update: intraday sweep judged on 5m candles (default)
`INTRADAY_SWEEP = "5m"` in `ifvg_1h.py` (env `INTRADAY_SWEEP=4h` restores the 4H wick): a Rule 1 level is swept when a **5m candle wicks through it and closes back**
(`SWEEP5M_MODE=a`, default; `ab` adds a close-beyond + two-displacement-candles case that was tested and not adopted). The first event uses the level up; the setup
continues on the 4H candle containing the confirmation. Implemented in `swings.add_break_times_5m`. Test: `sw5_experiments.py`.
2021-2026 intraday (GoatFunded / Pepperstone): 76 / 80 -> 78 / 85 trades, PF 1.32 / 2.13 -> 1.29 / 2.14, +13.1R / +42.4R -> +12.1R / +44.0R, max DD 9.6% / 7.4% -> 10.6% / 7.6%.
Both models: 331 / 362 trades, +76.6R / +126.1R, $20,620 / $33,262, max DD 12.3% / 12.7%.

## Update: intraday 5m sweep - case B added (default `SWEEP5M_MODE = "ab12"`)
A Rule 1 level is swept when (A) a 5m candle wicks through it and closes back, or (B) 1 or 2 5m candles close beyond it (not 3+) and are immediately followed by two
strong displacement 5m candles in the reversal direction (together >= 1 ATR14), the second one closing beyond the low (high level) / high (low level) of the last
sweeping candle. (`a` = case A only; `ab` = case B with a single sweeping candle.) Results are identical to case A only on both brokers: when price closes beyond a level
and is reversed by two strong candles, a wick-and-close-back of the same level almost always confirms first, so case B adds no new setups.
2021-2026 intraday (GoatFunded / Pepperstone): 78 / 85 trades, PF 1.29 / 2.14, +12.1R / +44.0R, max DD 10.6% / 7.6%. Both models: +76.6R / +126.1R, $20,620 / $33,262.

