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

for h in (6, 9, 18, 36, 48, 72):
    intraday(f"5m trigger window 12 -> {h} h", trig=h)
pd.DataFrame(rows).to_csv(f"output/trig_{S.DATA_SOURCE}.csv", index=False)
