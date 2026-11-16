"""Swing sweep (close-back rejection) judged on 5m / 15m / 1H / 4H. Swing model only.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python sweeptf_experiments.py
"""
import pandas as pd
import swing_snap as SN, swings as S
SN.SWEEP_DEF="sweep"
rows=[]
for tf in ("5m","15m","1H","4H"):
    S.SWEEP_TF=tf
    for r in SN.run().itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":tf,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net})
    print("done",tf,flush=True)
S.SWEEP_TF="1H"
pd.DataFrame(rows).to_csv(f"output/sweeptf_{S.DATA_SOURCE}.csv", index=False)
