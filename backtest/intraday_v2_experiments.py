"""Revised intraday entry (1H IFVG + 5m MSS, limit at the 1H IFVG touch on 5m) vs the current intraday entry.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python intraday_v2_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, intraday_v2 as V, swings as S
B.plot_trade = lambda *a, **k: None
rows = []
def add(name, df):
    for r in df.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "variant": name, "entry_time": r.entry_time, "exit": r.exit,
                     "r_net": r.r_net, "risk_pts": r.risk_pts})
with contextlib.redirect_stdout(io.StringIO()):
    t = B.run()
add("current: 5m MSS FVG touch", t[(t.entry_tf == "5m") & (t.entry_mode == "touch")])
for mode in ("before", "after", "none"):
    add(f"new: 1H IFVG touch, 5m MSS {mode}", V.run(mode))
    print("done", mode, flush=True)
pd.DataFrame(rows).to_csv(f"output/iv2_{S.DATA_SOURCE}.csv", index=False)
