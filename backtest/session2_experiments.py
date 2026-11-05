"""Session highs/lows, kept only if they are also a swing on 1H / 4H+ . Both models, LONDON/NY (least-bad session set).
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python session2_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, swing_snap as SN, swings as S
B.plot_trade = lambda *a, **k: None
SESS=("LONDON","NY")
rows=[]
def add(model,name,df):
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"model":model,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net})
    print("done",model,name,flush=True)
add("swing","baseline",SN.run())
for mt,lab in ((("1H",),"1H swing"),(("4H","D","W","M"),"4H+ swing")):
    SN.SESSION_LIQ,SN.SESSION_MIN_TF=SESS,mt; add("swing",f"+ session @ {lab}",SN.run()); SN.SESSION_LIQ,SN.SESSION_MIN_TF=(),("1H",)
def intr(sess,mt):
    B.INTRADAY_SESSION_LIQ,B.INTRADAY_SESSION_MIN_TF=sess,mt
    with contextlib.redirect_stdout(io.StringIO()): t=B.run()
    B.INTRADAY_SESSION_LIQ,B.INTRADAY_SESSION_MIN_TF=(),("1H",)
    return t[(t.entry_tf=="5m")&(t.entry_mode=="touch")]
add("intraday","baseline",intr((),("1H",)))
for mt,lab in ((("1H",),"1H swing"),(("4H","D","W","M"),"4H+ swing")):
    add("intraday",f"+ session @ {lab}",intr(SESS,mt))
pd.DataFrame(rows).to_csv(f"output/session2_{S.DATA_SOURCE}.csv", index=False)
