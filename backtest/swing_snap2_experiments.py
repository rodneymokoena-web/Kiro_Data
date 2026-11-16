"""Swing rules from snapshot 2 (last 4H FVG of the leg, 1H close inversion + 1H MSS, entry at the 4H IFVG, stop above
the 1H OB of the drop's 1H FVG, target 1H swing low) vs the current swing model.
Usage: H4_GRID=tradingview DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python swing_snap2_experiments.py
"""
import contextlib, io
import pandas as pd
import swing as W, swing_snap as SN, swings as S
W.plot_trade = lambda *a, **k: None
rows = []
def add(name, df):
    for r in df.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "grid": S.H4_GRID, "variant": name, "entry_time": r.entry_time,
                     "exit": r.exit, "r_net": r.r_net, "risk_pts": r.risk_pts})
with contextlib.redirect_stdout(io.StringIO()):
    w, _ = W.run()
add("A current swing model", w[(w.entry_type == "1H touch") & (w.stop_type == W.MAIN_STOP) & (w.target_type == "3R")])
for dm in (1, 2):
    for lvl in ("high", "50%"):
        for tgt in ("3R", "1H swing low", "D/W liquidity"):
            add(f"N disp {dm}c, stop OB {lvl}, target {tgt}",
                SN.run("1H OB of drop FVG", target=tgt, setups_kind="1H close", disp_min=dm, ob_level=lvl))
    print("done", dm, flush=True)
pd.DataFrame(rows).to_csv(f"output/snap2_{S.H4_GRID}_{S.DATA_SOURCE}.csv", index=False)
