"""Add previous-session highs/lows to Rule 1, both models, vs the current 4H/D/W/M.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python session_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, swing_snap as SN, swings as S
B.plot_trade = lambda *a, **k: None
rows=[]
def add(model,name,df):
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"model":model,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net})
    print("done",model,name,flush=True)
add("swing","baseline (no sessions)",SN.run(swing_1h_pivot=0))
for sess in (("ASIA","LONDON","NY"),("LONDON","NY"),("NY",)):
    SN.SESSION_LIQ=sess; add("swing","+ "+"/".join(sess),SN.run()); SN.SESSION_LIQ=()
def intr(sess):
    B.INTRADAY_SESSION_LIQ=sess
    with contextlib.redirect_stdout(io.StringIO()): t=B.run()
    B.INTRADAY_SESSION_LIQ=()
    return t[(t.entry_tf=="5m")&(t.entry_mode=="touch")]
add("intraday","baseline (no sessions)",intr(()))
for sess in (("ASIA","LONDON","NY"),("LONDON","NY"),("NY",)):
    add("intraday","+ "+"/".join(sess),intr(sess))
pd.DataFrame(rows).to_csv(f"output/session_{S.DATA_SOURCE}.csv", index=False)
