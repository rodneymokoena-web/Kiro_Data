"""Rule 1b: 4H swing sweeps traded with a 1H FVG -> 1H IFVG. Both models, 4H pivot 2 / 5 / 10, vs the current rules.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule1b_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, swing_snap as SN, swings as S
B.plot_trade = lambda *a, **k: None
rows = []
def add(model, name, df):
    for r in df.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "model": model, "variant": name, "entry_time": r.entry_time,
                     "exit": r.exit, "r_net": r.r_net})
add("swing", "D/W/M (current)", SN.run(swing_4h_pivot=0))
for piv in (2, 5, 10):
    add("swing", f"D/W/M + 4H({piv}) via 1H FVG", SN.run(swing_4h_pivot=piv))
print("swing done", flush=True)
def intraday(liq, mode, piv):
    B.INTRADAY_LIQ_TFS, B.INTRADAY_4H_MODE, B.INTRADAY_4H_PIVOT = liq, mode, piv
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run()
    return t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
add("intraday", "D/W/M only", intraday(("M", "W", "D"), "4H FVG", 10))
add("intraday", "D/W/M + 4H(10) via 4H FVG (current)", intraday(("M", "W", "D", "4H"), "4H FVG", 10))
for piv in (2, 5, 10):
    add("intraday", f"D/W/M + 4H({piv}) via 1H FVG", intraday(("M", "W", "D", "4H"), "1H FVG", piv))
print("intraday done", flush=True)
pd.DataFrame(rows).to_csv(f"output/r1b_{S.DATA_SOURCE}.csv", index=False)
