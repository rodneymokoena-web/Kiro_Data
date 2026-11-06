"""Rule 1 liquidity: D/W/M vs 4H/D/W/M swing levels, both models (swing = swing_snap, intraday = backtest).
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule1_4h_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, ifvg, swing_snap as SN, swings as S
B.plot_trade = lambda *a, **k: None
rows = []
for name, tfs in (("D/W/M (current)", ("M", "W", "D")), ("4H/D/W/M", ("M", "W", "D", "4H"))):
    ifvg.SWEEP_TFS = tfs
    sw = SN.run()
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run()
    t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
    for model, df in (("swing", sw), ("intraday", t)):
        for r in df.itertuples(index=False):
            rows.append({"source": S.DATA_SOURCE, "variant": name, "model": model, "entry_time": r.entry_time,
                         "exit": r.exit, "r_net": r.r_net})
    print("done", name, len(sw), len(t), flush=True)
pd.DataFrame(rows).to_csv(f"output/r1_4h_{S.DATA_SOURCE}.csv", index=False)
