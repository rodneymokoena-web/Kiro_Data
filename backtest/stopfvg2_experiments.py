"""Swing stop beyond the 1H FVG that sits above/below the 4H IFVG (fallback: current 1H OB 50%).
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python stopfvg2_experiments.py
"""
import pandas as pd
import swing_snap as SN, swings as S
rows=[]
def add(name,pick,overlap):
    SN.FVG_PICK, SN.FVG_OVERLAP = pick, overlap
    df=SN.run(stop_kind="1H FVG beyond IFVG", target="1H swing low")
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net,"risk_pts":r.risk_pts,"stop_from":r.stop_from})
    print("done",name,len(df),flush=True)
for r in SN.run(stop_kind="1H OB of drop FVG", target="1H swing low").itertuples(index=False):
    rows.append({"source":S.DATA_SOURCE,"variant":"current: 1H OB 50%","entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net,"risk_pts":r.risk_pts,"stop_from":r.stop_from})
add("1H FVG nearest, outside IFVG","nearest","outside")
add("1H FVG nearest, overlapping IFVG","nearest","overlap")
add("1H FVG farthest, outside IFVG","farthest","outside")
pd.DataFrame(rows).to_csv(f"output/stopfvg2_{S.DATA_SOURCE}.csv", index=False)
