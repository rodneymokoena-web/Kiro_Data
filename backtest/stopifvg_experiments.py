"""Swing stop beyond the 4H IFVG far edge vs the current 1H OB 50%, with each target.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python stopifvg_experiments.py
"""
import pandas as pd
import swing_snap as SN, swings as S
rows=[]
def add(name,df):
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net,"risk_pts":r.risk_pts,"planned_rr":r.planned_rr})
    print("done",name,len(df),flush=True)
add("current: 1H OB 50%, target 1H swing low", SN.run(stop_kind="1H OB of drop FVG", target="1H swing low"))
add("4H IFVG stop, target 1H swing low", SN.run(stop_kind="4H IFVG", target="1H swing low"))
add("4H IFVG stop, target 3R", SN.run(stop_kind="4H IFVG", target="3R"))
add("4H IFVG stop, target 4H(2) liquidity >=1R", SN.run(stop_kind="4H IFVG", target="liquidity", liq_tfs=("4H",), liq_pivot4=2, liq_min_rr=1.0))
pd.DataFrame(rows).to_csv(f"output/stopifvg_{S.DATA_SOURCE}.csv", index=False)
