"""4H liquidity = significant 4H swings (at a POI) vs all 4H(10) swings. Both models, current rules.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python sig4h_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, ifvg, swing_snap as SN, swings as S
B.plot_trade=lambda*a,**k:None; SN.plot_trade=lambda*a,**k:None
rows=[]
def add(model,name,df):
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"model":model,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net})
    print("done",model,name,len(df),flush=True)
add("swing","4H(10) all swings",SN.run())
with contextlib.redirect_stdout(io.StringIO()): t=B.run()
add("intraday","4H(10) all swings",t[(t.entry_tf=="5m")&(t.entry_mode=="touch")])
ifvg.SIG_4H=True
add("swing","significant 4H",SN.run())
with contextlib.redirect_stdout(io.StringIO()): t=B.run()
add("intraday","significant 4H",t[(t.entry_tf=="5m")&(t.entry_mode=="touch")])
ifvg.SIG_4H=False
pd.DataFrame(rows).to_csv(f"output/sig4h_{S.DATA_SOURCE}.csv", index=False)
