"""Sweep definition: "wick" (current) vs "sweep" (wick through AND close back). Both models, current rules.
Usage: BREAK_ON is read from env; this script sets swings.BREAK_ON directly.
"""
import contextlib, io
import pandas as pd
import backtest as B, swing_snap as SN, swings as S
B.plot_trade=lambda*a,**k:None; SN.plot_trade=lambda*a,**k:None
rows=[]
def add(model,name,df):
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"model":model,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net})
    print("done",model,name,len(df),flush=True)
def intr():
    with contextlib.redirect_stdout(io.StringIO()): t=B.run()
    return t[(t.entry_tf=="5m")&(t.entry_mode=="touch")]
for mode in ("wick","sweep"):
    S.BREAK_ON=mode
    add("swing",f"{mode}",SN.run())
    add("intraday",f"{mode}",intr())
S.BREAK_ON="wick"
pd.DataFrame(rows).to_csv(f"output/sweep_{S.DATA_SOURCE}.csv", index=False)
