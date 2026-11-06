"""Swing target = previous 4H or Daily high/low (nearest opposite liquidity) vs current 1H swing low.
Current rules (close-back sweep). Usage: DATA_SOURCE=.. TEST_START=.. .venv/bin/python target4hd_experiments.py
"""
import pandas as pd
import swing_snap as SN, swings as S
rows=[]
def add(name,df):
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net,"planned_rr":r.planned_rr})
    print("done",name,len(df),flush=True)
add("current: 1H swing low", SN.run(target="1H swing low"))
add("4H/D liquidity (4H piv2)", SN.run(target="liquidity", liq_tfs=("4H","D"), liq_pivot4=2))
add("4H/D liquidity (4H piv2, >=1R)", SN.run(target="liquidity", liq_tfs=("4H","D"), liq_pivot4=2, liq_min_rr=1.0))
add("4H/D liquidity (4H piv10)", SN.run(target="liquidity", liq_tfs=("4H","D"), liq_pivot4=10))
add("4H only liquidity (piv2)", SN.run(target="liquidity", liq_tfs=("4H",), liq_pivot4=2))
add("D only liquidity", SN.run(target="liquidity", liq_tfs=("D",)))
pd.DataFrame(rows).to_csv(f"output/target4hd_{S.DATA_SOURCE}.csv", index=False)
