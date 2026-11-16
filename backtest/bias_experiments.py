"""Rule 1 bias filter variants on swing + intraday. Usage: DATA_SOURCE=.. TEST_START=.. python bias_experiments.py"""
import contextlib, io
import pandas as pd
import backtest as B, swing_snap as SN, swings as S, bias
B.plot_trade = lambda *a, **k: None
rows = []
VARS = [("0 baseline (no bias)", None), ("1 sweep+FVG 500", dict(sweep=True, fvg=True, bars=500)),
        ("2 sweep only 500", dict(sweep=True, fvg=False, bars=500)), ("3 FVG only 500", dict(sweep=False, fvg=True, bars=500)),
        ("4 sweep+FVG 250", dict(sweep=True, fvg=True, bars=250)), ("5 sweep+FVG 1000", dict(sweep=True, fvg=True, bars=1000))]
for name, kw in VARS:
    bias.BIAS_FILTER = kw is not None
    if kw:
        bias.BIAS_SWEEP, bias.BIAS_FVG, bias.BIAS_BARS = kw["sweep"], kw["fvg"], kw["bars"]
    bias._cache.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        sw = SN.run()
        it = B.run()
    it = it[(it.entry_tf == "5m") & (it.entry_mode == "touch")]
    for model, d in (("swing", sw), ("intraday", it)):
        for r in d.itertuples(index=False):
            rows.append({"source": S.DATA_SOURCE, "variant": name, "model": model, "entry_time": r.entry_time, "exit": r.exit, "r_net": r.r_net})
    print("done", name, len(sw), len(it), flush=True)
pd.DataFrame(rows).to_csv(f"output/bias_{S.DATA_SOURCE}.csv", index=False)
