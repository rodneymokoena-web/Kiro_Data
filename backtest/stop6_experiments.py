"""Six swing stop options vs the current 1H OB 50%. Group A or B (parallel runs).
Usage: DATA_SOURCE=.. TEST_START=.. .venv/bin/python stop6_experiments.py A|B
"""
import sys
import pandas as pd
import swing_snap as SN, swings as S
grp = sys.argv[1]
rows = []
def add(name, **kw):
    SN.EXTRA_ATR_MULT = kw.pop("atr", 0.0); SN.TRAIL_MODE = kw.pop("trail", "")
    df = SN.run(**kw)
    SN.EXTRA_ATR_MULT = 0.0; SN.TRAIL_MODE = ""
    for r in df.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "variant": name, "entry_time": r.entry_time, "exit": r.exit,
                     "r_net": r.r_net, "risk_pts": r.risk_pts})
    print("done", name, len(df), flush=True)
OB = "1H OB of drop FVG"
if grp == "A":
    add("0 current: 1H OB 50%", stop_kind=OB)
    add("1 4H order block", stop_kind="4H OB leg")
    add("2 previous 1H candle", stop_kind="prev 1H candle")
    add("3a OB 50% + 0.25 ATR", stop_kind=OB, atr=0.25)
    add("3b OB 50% + 0.5 ATR", stop_kind=OB, atr=0.5)
    add("3c OB 50% + 1.0 ATR", stop_kind=OB, atr=1.0)
else:
    add("4a sweep extreme (+2 pts)", stop_kind="4H extreme")
    add("4b sweep extreme + 0.25 ATR", stop_kind="4H extreme", atr=0.25)
    add("5a OB 50% + BE + structure trail", stop_kind=OB, trail="A")
    add("5b OB 50% + trail after +1R", stop_kind=OB, trail="B")
    add("6a swept level (outermost)", stop_kind="swept level outer")
    add("6b swept level (nearest)", stop_kind="swept level near")
pd.DataFrame(rows).to_csv(f"output/stop6_{grp}_{S.DATA_SOURCE}.csv", index=False)
