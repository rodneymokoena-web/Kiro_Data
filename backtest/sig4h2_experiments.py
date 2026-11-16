"""4H liquidity: (a) 4H(10) all, (b) 4H(2) all, (c) 4H(2) filtered to significant. Both models, current rules.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python sig4h2_experiments.py
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
def intr():
    with contextlib.redirect_stdout(io.StringIO()): t=B.run()
    return t[(t.entry_tf=="5m")&(t.entry_mode=="touch")]
# (a) 4H(10) all
SN.RULE1_4H_PIVOT=10; B.INTRADAY_4H_PIVOT=10; ifvg.SIG_4H=False
add("swing","4H(10) all",SN.run()); add("intraday","4H(10) all",intr())
# (b) 4H(2) all
SN.RULE1_4H_PIVOT=2; B.INTRADAY_4H_PIVOT=2; ifvg.SIG_4H=False
add("swing","4H(2) all",SN.run()); add("intraday","4H(2) all",intr())
# (c) 4H(2) significant
ifvg.SIG_4H=True
add("swing","4H(2) significant",SN.run()); add("intraday","4H(2) significant",intr())
ifvg.SIG_4H=False; SN.RULE1_4H_PIVOT=10; B.INTRADAY_4H_PIVOT=10
pd.DataFrame(rows).to_csv(f"output/sig4h2_{S.DATA_SOURCE}.csv", index=False)
