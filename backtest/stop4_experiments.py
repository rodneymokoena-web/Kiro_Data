"""Intraday stop: 5m order block (of the 4H sweeping leg / of the intraday retest leg) vs the previous 1H candle.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python stop4_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, stops_ext, swings as S
B.plot_trade = lambda *a, **k: None
rows = []
for mode in ("prev_1h_candle", *stops_ext.LTF_KINDS):
    B.STOP_MODE = mode
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run()
    t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
    name = "prev 1H candle (current)" if mode == "prev_1h_candle" else mode
    for r in t.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "variant": name, "model": "intraday", "entry_time": r.entry_time,
                     "exit": r.exit, "r_net": r.r_net, "risk_pts": r.risk_pts, "fallback": r.stop_fallback})
    print("done", mode, flush=True)
pd.DataFrame(rows).to_csv(f"output/stop4_{S.DATA_SOURCE}.csv", index=False)
