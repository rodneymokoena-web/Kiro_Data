"""Swing stop = just beyond the far edge of the 4H IFVG + a % buffer, vs the current 1H OB 50%.
Usage: DATA_SOURCE=.. TEST_START=.. .venv/bin/python stopifvgbuf_experiments.py
"""
import pandas as pd
import swing_snap as SN, swings as S
rows=[]
def add(name,df):
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net,"risk_pts":r.risk_pts})
    print("done",name,len(df),flush=True)
add("current: 1H OB 50%", SN.run(stop_kind="1H OB of drop FVG"))
SN.IFVG_BUF_MODE="height"
for pct in (5,25,50,100):
    SN.IFVG_BUF_PCT=pct
    add(f"IFVG far edge + {pct}% of IFVG height", SN.run(stop_kind="4H IFVG + buffer"))
SN.IFVG_BUF_MODE="price"; SN.IFVG_BUF_PCT=5.0
add("IFVG far edge + 5% of price", SN.run(stop_kind="4H IFVG + buffer"))
pd.DataFrame(rows).to_csv(f"output/stopifvgbuf_{S.DATA_SOURCE}.csv", index=False)
