"""4H swing pivot 2 vs 10 (both models, current rules incl. sessions).
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python r1piv_experiments.py
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
for piv in (10,2):
    SN.RULE1_4H_PIVOT=piv
    add("swing",f"4H({piv})",SN.run())
    B.INTRADAY_4H_PIVOT=piv
    with contextlib.redirect_stdout(io.StringIO()): t=B.run()
    add("intraday",f"4H({piv})",t[(t.entry_tf=="5m")&(t.entry_mode=="touch")])
B.INTRADAY_4H_PIVOT=10; SN.RULE1_4H_PIVOT=10
pd.DataFrame(rows).to_csv(f"output/r1piv_{S.DATA_SOURCE}.csv", index=False)
