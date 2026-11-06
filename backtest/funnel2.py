"""Where do sweeps / setups drop out? Funnel for the current swing and intraday models.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python funnel2.py
"""
import contextlib, io
import pandas as pd
import backtest as B, ifvg, ifvg_1h, setups_v3 as V3, swing_snap as SN, swings as S
B.plot_trade = lambda *a, **k: None
h1 = S.load(S.DATA / S.SYMBOLS["US100"][0])
htf = {tf: S.build_htf(h1, tf) for tf in ("D", "W", "M")}
lv = pd.concat([S.find_swings(htf[tf], tf) for tf in ("M", "W", "D")], ignore_index=True)
lv = S.add_break_times(lv, h1)
t0 = max(S.TEST_START, h1.index[0])
print(f"{S.DATA_SOURCE}: D/W/M swing levels formed {len(lv)}, broken (swept) since {t0.date()}: {int((lv.broken_time >= t0).sum())}")
V3.STATS.clear(); SN.LOST.clear()
with contextlib.redirect_stdout(io.StringIO()):
    sw = SN.run()
print("\nSWING model funnel (a level can be swept once; several levels can share one setup)")
for k, v in sorted(V3.STATS.items()):
    print(f"  {k:48s} {v}")
print(f"  {'7 trades taken':48s} {len(sw)}")
for k, v in SN.LOST.items():
    print(f"     lost at entry/stop stage: {k}: {v}")
print("\nINTRADAY model funnel")
with contextlib.redirect_stdout(io.StringIO()):
    h4, st = B._intraday_setups(h1)
f = ifvg.find_fvgs(h1)
r5 = [ifvg_1h.find_1h_ifvg(x, h1, f) for x in st]
import collections
cnt = collections.Counter(x["status"] for x in r5)
print(f"  4H setups (sweep -> 4H FVG inverted by 4H close, displacement + 1H MSS): {len(st)}")
for k, v in cnt.items():
    print(f"     1H IFVG stage: {k}: {v}")
with contextlib.redirect_stdout(io.StringIO()):
    t = B.run()
nt = pd.read_csv(B.OUT / "not_traded.csv")
print("     entry stage (5m retest -> 5m MSS -> FVG limit), reasons not traded:")
for k, v in nt.reason.value_counts().items():
    print(f"        {k}: {v}")
t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
print(f"  trades taken: {len(t)}")
