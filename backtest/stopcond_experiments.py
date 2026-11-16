"""Swing stop: inversion-candle high/low when 1H displacement >= N ATR, else 1H OB 50%. N = 2.0 / 2.5 / 3.0.
Also compare always-inversion-candle. Usage: DATA_SOURCE=.. TEST_START=.. .venv/bin/python stopcond_experiments.py
"""
import pandas as pd
import swing_snap as SN, swings as S
rows=[]
def add(name,df):
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net,"risk_pts":r.risk_pts,"stop_from":r.stop_from})
    print("done",name,len(df),flush=True)
add("current 1H OB 50%", SN.run(stop_kind="1H OB of drop FVG"))
for n in (2.0,2.5,3.0):
    SN.STOP_DISP_ATR=n
    add(f"inv candle if disp>={n}ATR else OB", SN.run(stop_kind="inv candle if disp>=ATR"))
SN.STOP_DISP_ATR=0.0
add("inv candle always", SN.run(stop_kind="inv candle if disp>=ATR"))
SN.STOP_DISP_ATR=2.5
pd.DataFrame(rows).to_csv(f"output/stopcond_{S.DATA_SOURCE}.csv", index=False)
