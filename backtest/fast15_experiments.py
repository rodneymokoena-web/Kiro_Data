"""Fast intraday path (sweep -> 15m FVG inverted -> 15m CISD/MSS -> 5m entry) vs the current intraday model.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python fast15_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, setups_15m as F, swings as S
B.plot_trade = lambda *a, **k: None
rows=[]
def run(name, fast, **kw):
    B.INTRADAY_FAST15=fast
    for k,v in kw.items(): setattr(F,k,v)
    with contextlib.redirect_stdout(io.StringIO()): t=B.run()
    B.INTRADAY_FAST15=""
    t=t[(t.entry_tf=="5m")&(t.entry_mode=="touch")]
    for r in t.itertuples(index=False):
        rows.append({"source":S.DATA_SOURCE,"variant":name,"entry_time":r.entry_time,"exit":r.exit,"r_net":r.r_net})
    print("done",name,len(t),flush=True)
run("current 4H->1H->5m","")
run("+ fast15 (CISD+MSS)","add",REQUIRE_CISD=True,REQUIRE_MSS=True)
run("fast15 only (CISD+MSS)","only",REQUIRE_CISD=True,REQUIRE_MSS=True)
run("fast15 only (CISD, no MSS)","only",REQUIRE_CISD=True,REQUIRE_MSS=False)
pd.DataFrame(rows).to_csv(f"output/fast15_{S.DATA_SOURCE}.csv", index=False)
