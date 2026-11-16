"""Snapshot swing rules: stop above the 1H OB touch (near edge) vs its 50% vs its high.
Usage: H4_GRID=tradingview DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python swing_snap3_experiments.py
"""
import pandas as pd
import swing_snap as SN, swings as S
rows = []
for lvl in ("touch", "50%", "high"):
    for tgt in ("1H swing low", "3R"):
        t = SN.run("1H OB of drop FVG", target=tgt, setups_kind="1H close", disp_min=1, ob_level=lvl)
        for r in t.itertuples(index=False):
            rows.append({"source": S.DATA_SOURCE, "variant": f"stop OB {lvl}, target {tgt}", "entry_time": r.entry_time,
                         "exit": r.exit, "r_net": r.r_net, "risk_pts": r.risk_pts, "stop_from": r.stop_from})
    print("done", lvl, flush=True)
pd.DataFrame(rows).to_csv(f"output/snap3_{S.DATA_SOURCE}.csv", index=False)
