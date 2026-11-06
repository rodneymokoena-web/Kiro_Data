"""Fast 15m path (sweep -> 15m IFVG -> 15m CISD+MSS -> 15m entry FVG), matching the chart, vs the current model.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python fast15b_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, entry_ltf as E, setups_15m as F, swings as S
B.plot_trade = lambda *a, **k: None
F.REQUIRE_CISD=True; F.REQUIRE_MSS=True
rows=[]
def run(name, fast, entry):
    B.INTRADAY_FAST15=fast; E.ENTRY_FILTER=[entry]
    with contextlib.redirect_stdout(io.StringIO()): t=B.run()
    B.INTRADAY_FAST15=""
    tf,md=entry.split(); t=t[(t.entry_tf==tf)&(t.entry_mode==md)]
    for r in t.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net})
    print("done",name,len(t),flush=True)
run("current 4H->1H->5m touch","","5m touch")
run("fast15 only, 15m entry","only","15m touch")
run("fast15 only, 5m entry","only","5m touch")
run("+ fast15, 15m entry","add","15m touch")
pd.DataFrame(rows).to_csv(f"output/fast15b_{S.DATA_SOURCE}.csv", index=False)
