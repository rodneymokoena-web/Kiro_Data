"""Fast 15m path, 5m entry, 15m displacement >= 2.5 ATR: as the only intraday model and added to the current one.
Also the combined account with the swing model. Usage: DATA_SOURCE=.. TEST_START=.. .venv/bin/python fast15final.py
"""
import contextlib, io
import pandas as pd
import backtest as B, entry_ltf as E, setups_15m as F, structure, swing_snap as SN, swings as S
B.plot_trade = lambda *a, **k: None; SN.plot_trade = lambda *a,**k: None
F.REQUIRE_CISD=True; F.REQUIRE_MSS=True; E.ENTRY_FILTER=["5m touch"]
rows=[]
def intr(fast,atr):
    B.INTRADAY_FAST15=fast; sv=structure.DISP_MIN_ATR; structure.DISP_MIN_ATR=atr
    with contextlib.redirect_stdout(io.StringIO()): t=B.run()
    structure.DISP_MIN_ATR=sv; B.INTRADAY_FAST15=""
    return t[(t.entry_tf=="5m")&(t.entry_mode=="touch")]
def add(name,df):
    for r in df.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net})
    print("done",name,len(df),flush=True)
cur=intr("",1.0); add("intraday current",cur)
fo=intr("only",2.5); add("intraday fast15 only (5m,2.5ATR)",fo)
fa=intr("add",2.5); add("intraday current + fast15 (5m,2.5ATR)",fa)
with contextlib.redirect_stdout(io.StringIO()): sw=SN.run()
add("swing",sw)
pd.DataFrame(rows).to_csv(f"output/fast15final_{S.DATA_SOURCE}.csv", index=False)
