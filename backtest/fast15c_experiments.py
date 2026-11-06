"""Fast 15m path with a larger 15m displacement requirement (>= N ATR). CISD+MSS on. 15m and 5m entry.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python fast15c_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, entry_ltf as E, setups_15m as F, structure, swings as S
B.plot_trade = lambda *a, **k: None
F.REQUIRE_CISD=True; F.REQUIRE_MSS=True
rows=[]
def run(name, entry, atr):
    B.INTRADAY_FAST15="only"; E.ENTRY_FILTER=[entry]
    saved=structure.DISP_MIN_ATR
    # setups_15m sets DISP_MIN_CANDLES in its own try/finally; the ATR threshold is global on structure
    structure.DISP_MIN_ATR=atr
    with contextlib.redirect_stdout(io.StringIO()): t=B.run()
    structure.DISP_MIN_ATR=saved; B.INTRADAY_FAST15=""
    tf,md=entry.split(); t=t[(t.entry_tf==tf)&(t.entry_mode==md)]
    for r in t.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net})
    print("done",name,len(t),flush=True)
for atr in (1.0,1.5,2.0,2.5):
    run(f"15m entry, disp>={atr}ATR","15m touch",atr)
    run(f"5m entry, disp>={atr}ATR","5m touch",atr)
pd.DataFrame(rows).to_csv(f"output/fast15c_{S.DATA_SOURCE}.csv", index=False)
