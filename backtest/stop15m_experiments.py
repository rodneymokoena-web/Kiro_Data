"""Swing stop = previous 15m candle high/low vs current 1H OB 50%. Current rules. 1H-swing-low and 3R targets.
Usage: DATA_SOURCE=.. TEST_START=.. .venv/bin/python stop15m_experiments.py
"""
import pandas as pd
import swing_snap as SN, swings as S
rows=[]
def add(name,df):
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net,"risk_pts":r.risk_pts})
    print("done",name,len(df),flush=True)
add("current 1H OB 50%, 1H swing low", SN.run(stop_kind="1H OB of drop FVG", target="1H swing low"))
add("prev 15m candle, 1H swing low", SN.run(stop_kind="prev 15m candle", target="1H swing low"))
add("prev 15m candle, 3R", SN.run(stop_kind="prev 15m candle", target="3R"))
add("prev 15m candle, 4H/D liquidity", SN.run(stop_kind="prev 15m candle", target="liquidity", liq_tfs=("4H","D"), liq_pivot4=2))
pd.DataFrame(rows).to_csv(f"output/stop15m_{S.DATA_SOURCE}.csv", index=False)
