"""Intraday only: add session highs/lows that are also a swing on 1H / 4H+, across session sets. Swing model unchanged.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python session_intraday_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, swings as S
B.plot_trade = lambda *a, **k: None
rows=[]
def intr(sess,mt):
    B.INTRADAY_SESSION_LIQ,B.INTRADAY_SESSION_MIN_TF=sess,mt
    with contextlib.redirect_stdout(io.StringIO()): t=B.run()
    B.INTRADAY_SESSION_LIQ,B.INTRADAY_SESSION_MIN_TF=(),("1H",)
    return t[(t.entry_tf=="5m")&(t.entry_mode=="touch")]
def add(name,df):
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net})
    print("done",name,flush=True)
add("baseline (no sessions)",intr((),("1H",)))
for sess in (("ASIA","LONDON","NY"),("LONDON","NY"),("NY",)):
    tag="/".join(sess)
    add(f"{tag} @ 1H+ swing",intr(sess,("1H","4H","D","W","M")))
    add(f"{tag} @ 4H+ swing",intr(sess,("4H","D","W","M")))
pd.DataFrame(rows).to_csv(f"output/sessintr_{S.DATA_SOURCE}.csv", index=False)
