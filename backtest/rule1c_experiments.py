"""Rule 1c: 1H swing sweeps -> 1H FVG -> 1H IFVG, both models, 1H pivot 5 / 10 / 20 vs the current rules.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule1c_experiments.py
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
add("swing", "current", SN.run(swing_1h_pivot=0))
for piv in (5, 10, 20):
    add("swing", f"+ 1H({piv})", SN.run(swing_1h_pivot=piv))
    print("swing", piv, flush=True)
def intraday(piv):
    B.INTRADAY_1H_PIVOT = piv
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run()
    return t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
add("intraday", "current", intraday(0))
for piv in (5, 10, 20):
    add("intraday", f"+ 1H({piv})", intraday(piv))
    print("intraday", piv, flush=True)
pd.DataFrame(rows).to_csv(f"output/r1c_{S.DATA_SOURCE}.csv", index=False)
