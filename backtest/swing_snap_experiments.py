"""Swing model from the user's chart (entry at the 4H IFVG, stop above the 1H OB above the 1H FVG above the 4H IFVG)
vs the current swing model. Usage: H4_GRID=tradingview DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python swing_snap_experiments.py
"""
import contextlib, io
import pandas as pd
import swing as W, swing_snap as SN, swings as S
W.plot_trade = lambda *a, **k: None
rows = []
def add(name, df, rcol="r_net"):
    for r in df.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "grid": S.H4_GRID, "variant": name, "model": "swing",
                     "entry_time": r.entry_time, "exit": r.exit, "r_net": getattr(r, rcol), "risk_pts": r.risk_pts})
with contextlib.redirect_stdout(io.StringIO()):
    w, _ = W.run()
add("A current: 1H IFVG entry, 4H OB stop, 3R",
    w[(w.entry_type == "1H touch") & (w.stop_type == W.MAIN_STOP) & (w.target_type == "3R")])
for tgt in ("3R", "D/W liquidity"):
    for pick in ("nearest", "last"):
        for ob in ("bull", "bear"):
            add(f"S 4H IFVG entry, 1H {ob} OB {pick} above 1H FVG, {tgt}", SN.run("1H OB above 1H FVG", ob, tgt, pick))
    add(f"S 4H IFVG entry, 4H OB stop, {tgt}", SN.run("4H OB disp", "bull", tgt))
    print("done", tgt, flush=True)
pd.DataFrame(rows).to_csv(f"output/snap_{S.H4_GRID}_{S.DATA_SOURCE}.csv", index=False)
