"""Every swing and intraday setup (the signals, not just trades), tagged with whether it became a trade.
Usage: DATA_SOURCE=pepperstone / pepperstone_oos TEST_START=.. .venv/bin/python all_setups.py
"""
import contextlib, io
import pandas as pd, numpy as np
import backtest as B, ifvg, ifvg_1h, swing_snap as SN, swings as S
B.plot_trade=lambda*a,**k:None; SN.plot_trade=lambda*a,**k:None
h1=S.load(S.DATA/S.SYMBOLS["US100"][0])
t0=max(S.TEST_START,h1.index[0])
# --- SWING setups + which filled ---
with contextlib.redirect_stdout(io.StringIO()):
    _,sw_setups=SN._setups_1h_close(h1,SN.DISP_MIN_1H)
    sw_trades=SN.run()
sw=pd.DataFrame(sw_setups); sw["signal_time"]=pd.to_datetime(sw["signal_time"],utc=True)
sw=sw[sw.signal_time>=t0]
traded=set(pd.to_datetime(sw_trades["4h_signal_time"],utc=True)) if "4h_signal_time" in sw_trades else set()
# swing_snap stores signal_time; match setups to trades by signal_time
tr_times=set(pd.to_datetime(sw_trades["entry_time"],utc=True)) if len(sw_trades) else set()
res=sw_trades.set_index(pd.to_datetime(sw_trades["4h_signal_time"] if "4h_signal_time" in sw_trades else sw_trades["entry_time"],utc=True)) if len(sw_trades) else None
sw["model"]="swing"
# tag traded by signal_time present in trades' signal column
tcol="signal_time" if "signal_time" not in sw_trades.columns else "signal_time"
sig_col=pd.to_datetime(sw_trades["4h_signal_time"],utc=True)
sw["traded"]=sw.signal_time.isin(set(sig_col))
m={pd.Timestamp(t):(e,round(r,2)) for t,e,r in zip(sig_col,sw_trades["exit"],sw_trades["r_net"])}
sw["result"]=sw.signal_time.map(lambda t:f"{m[t][0]} {m[t][1]:+}R" if t in m else "")
# --- INTRADAY setups + which filled ---
with contextlib.redirect_stdout(io.StringIO()):
    h4,it_setups=B._intraday_setups(h1)
    it_trades=B.run()
it_trades=it_trades[(it_trades.entry_tf=="5m")&(it_trades.entry_mode=="touch")]
fv=ifvg.find_fvgs(h1); rows=[]
for st in it_setups:
    r5=ifvg_1h.find_1h_ifvg(st,h1,fv)
    sig=r5.get("h1_signal_time")
    rows.append({"signal_time":pd.Timestamp(sig) if sig==sig and sig is not None else pd.NaT,"signal":st["signal"],
                 "swept_levels":st["swept_levels"],"stage":r5["status"]})
it=pd.DataFrame(rows); it["signal_time"]=pd.to_datetime(it["signal_time"],utc=True)
it=it[it.signal_time>=t0]
it_sig=set(pd.to_datetime(it_trades["1h_signal_time"],utc=True)) if len(it_trades) else set()
mi={pd.Timestamp(t):(e,round(r,2)) for t,e,r in zip(pd.to_datetime(it_trades["1h_signal_time"],utc=True),it_trades["exit"],it_trades["r_net"])} if len(it_trades) else {}
it["traded"]=it.signal_time.isin(it_sig); it["result"]=it.signal_time.map(lambda t:f"{mi[t][0]} {mi[t][1]:+}R" if t in mi else "")
src=S.DATA_SOURCE
sw.to_csv(f"output/allsetups_swing_{src}.csv",index=False); it.to_csv(f"output/allsetups_intraday_{src}.csv",index=False)
print(f"{src}: swing setups {len(sw)} (traded {int(sw.traded.sum())}); intraday 1H-IFVG signals {int((it.stage=='signal').sum())} (traded {int(it.traded.sum())})")
