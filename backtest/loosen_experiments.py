"""Loosen one filter at a time. Swing = swing_snap, intraday = backtest. 4 data sets in parallel.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python loosen_experiments.py [swing|intraday]
"""
import contextlib, io, sys
import pandas as pd
import backtest as B, entry_ltf as E, ifvg, ifvg_1h as I, setups_v3 as V3, structure, swing_snap as SN, swings as S
B.plot_trade = lambda *a, **k: None
which = sys.argv[1] if len(sys.argv) > 1 else "both"
rows = []
def add(model, name, df):
    for r in df.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "model": model, "variant": name, "entry_time": r.entry_time,
                     "exit": r.exit, "r_net": r.r_net})
    print("done", model, name, len(df), flush=True)

def swing(name, **kw):
    saved = (V3.INVERT_WINDOW_1H, SN.RETEST_WINDOW, SN.LEG_LOOKBACK_4H, SN.REQUIRE_MSS, structure.DISP_MIN_ATR)
    V3.INVERT_WINDOW_1H = kw.get("window", saved[0]); SN.RETEST_WINDOW = pd.Timedelta(hours=kw.get("retest", 48))
    SN.LEG_LOOKBACK_4H = kw.get("lookback", saved[2]); SN.REQUIRE_MSS = kw.get("mss", saved[3])
    structure.DISP_MIN_ATR = kw.get("atr", saved[4])
    try:
        add("swing", name, SN.run(disp_min=kw.get("dmin", 1)))
    finally:
        V3.INVERT_WINDOW_1H, SN.RETEST_WINDOW, SN.LEG_LOOKBACK_4H, SN.REQUIRE_MSS, structure.DISP_MIN_ATR = saved

def intraday(name, **kw):
    saved = (I.RETEST_WINDOW, I.INVERT_WINDOW_1H, ifvg.INVERT_WINDOW, I.MSS_REQUIRED_4H, structure.DISP_MIN_CANDLES,
             structure.DISP_MIN_ATR, E.RETEST_WINDOW_1H, E.TRIGGER_WINDOW, E.FILL_WINDOW, ifvg.LEG_MAX_LOOKBACK)
    I.RETEST_WINDOW = pd.Timedelta(hours=kw.get("retest4", 48)); I.INVERT_WINDOW_1H = kw.get("inv1h", 20)
    ifvg.INVERT_WINDOW = kw.get("inv4h", 20); I.MSS_REQUIRED_4H = kw.get("mss", True)
    structure.DISP_MIN_CANDLES = kw.get("dmin", 2); structure.DISP_MIN_ATR = kw.get("atr", 1.0)
    E.RETEST_WINDOW_1H = pd.Timedelta(hours=kw.get("retest1", 24)); E.TRIGGER_WINDOW = pd.Timedelta(hours=kw.get("trig", 12))
    E.FILL_WINDOW = pd.Timedelta(hours=kw.get("fill", 12))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            t = B.run()
        add("intraday", name, t[(t.entry_tf == "5m") & (t.entry_mode == "touch")])
    finally:
        (I.RETEST_WINDOW, I.INVERT_WINDOW_1H, ifvg.INVERT_WINDOW, I.MSS_REQUIRED_4H, structure.DISP_MIN_CANDLES,
         structure.DISP_MIN_ATR, E.RETEST_WINDOW_1H, E.TRIGGER_WINDOW, E.FILL_WINDOW, ifvg.LEG_MAX_LOOKBACK) = saved

if which in ("both", "swing"):
    swing("baseline")
    swing("inversion window 80 -> 160 1H candles", window=160)
    swing("4H FVG lookback 60 -> 120 4H candles", lookback=120)
    swing("retest window 48 -> 96 h", retest=96)
    swing("no 1H MSS", mss="none")
    swing("displacement 1 ATR -> 0.5 ATR", atr=0.5)
    swing("no displacement requirement", atr=0.0)
    swing("window 160 + lookback 120 + retest 96", window=160, lookback=120, retest=96)
    swing("all loose: no MSS, 0.5 ATR, window 160, retest 96", mss="none", atr=0.5, window=160, retest=96)
if which in ("both", "intraday"):
    intraday("baseline")
    intraday("4H inversion window 20 -> 40 4H candles", inv4h=40)
    intraday("4H IFVG retest window 48 -> 96 h", retest4=96)
    intraday("1H IFVG window 20 -> 40 1H candles", inv1h=40)
    intraday("1H IFVG retest 24 -> 48 h", retest1=48)
    intraday("5m trigger window 12 -> 24 h", trig=24)
    intraday("entry order valid 12 -> 24 h", fill=24)
    intraday("no 1H MSS on the 4H inversion", mss=False)
    intraday("displacement 2 candles -> 1 (all timeframes)", dmin=1)
    intraday("all windows doubled", inv4h=40, retest4=96, inv1h=40, retest1=48, trig=24, fill=24)
pd.DataFrame(rows).to_csv(f"output/loosen_{which}_{S.DATA_SOURCE}.csv", index=False)
