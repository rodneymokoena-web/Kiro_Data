"""Swing Rule 1: 4H(10)/D/W/M vs the current D/W/M only.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule1swing_experiments.py
"""
import pandas as pd
import swing_snap as SN, swings as S
rows=[]
def add(name,tfs):
    SN.LIQ_TFS_RULE1=tfs
    for r in SN.run().itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net})
    print("done",name,flush=True)
add("D/W/M (current)",("M","W","D"))
add("4H(10)/D/W/M",("M","W","D","4H"))
pd.DataFrame(rows).to_csv(f"output/r1swing_{S.DATA_SOURCE}.csv", index=False)
