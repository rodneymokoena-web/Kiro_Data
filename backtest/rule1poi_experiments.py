"""Rules 1b / 1c with a POI: 4H sweeps only into a D FVG, 1H sweeps only into a 4H FVG (both via 1H FVG -> 1H IFVG),
on top of the current rules. Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule1poi_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, setups_4hsweep as X, swing_snap as SN, swings as S
B.plot_trade = lambda *a, **k: None
X.USE_POI = True
rows = []
def add(model, name, df):
    for r in df.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "model": model, "variant": name, "entry_time": r.entry_time,
                     "exit": r.exit, "r_net": r.r_net})
add("swing", "current", SN.run(swing_4h_pivot=0, swing_1h_pivot=0))
for p in (2, 5, 10):
    add("swing", f"+ 4H({p}) at D FVG", SN.run(swing_4h_pivot=p, swing_1h_pivot=0))
for p in (5, 10, 20):
    add("swing", f"+ 1H({p}) at 4H FVG", SN.run(swing_4h_pivot=0, swing_1h_pivot=p))
add("swing", "+ 4H(5) at D FVG + 1H(10) at 4H FVG", SN.run(swing_4h_pivot=5, swing_1h_pivot=10))
print("swing done", flush=True)
def intraday(layers):
    B.INTRADAY_POI_LAYERS = layers
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run()
    return t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
add("intraday", "current", intraday([]))
for p in (2, 5, 10):
    add("intraday", f"+ 4H({p}) at D FVG", intraday([("4H", p)]))
for p in (5, 10, 20):
    add("intraday", f"+ 1H({p}) at 4H FVG", intraday([("1H", p)]))
add("intraday", "+ 4H(5) at D FVG + 1H(10) at 4H FVG", intraday([("4H", 5), ("1H", 10)]))
print("intraday done", flush=True)
pd.DataFrame(rows).to_csv(f"output/r1poi_{S.DATA_SOURCE}.csv", index=False)
