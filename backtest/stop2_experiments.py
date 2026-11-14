"""New stops: above the 1H FVG (1H IFVG / highest 1H FVG above the 4H IFVG) vs the first order block of the 4H sweeping
leg, against the current stops. Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python stop2_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, stops_ext, swing as W, swings as S
B.plot_trade = lambda *a, **k: None
W.plot_trade = lambda *a, **k: None
rows = []
W.STOPS = ["4H extreme", *stops_ext.KINDS]
for r3 in ("4H close", "M6"):
    W.RULE3 = r3
    with contextlib.redirect_stdout(io.StringIO()):
        w, _ = W.run()
    w = w[(w.entry_type == "1H touch") & (w.target_type == "3R")]
    for r in w.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "variant": f"{r.stop_type}{' (current)' if r.stop_type == '4H extreme' else ''}",
                     "model": "swing" if r3 == "4H close" else "swing M6", "entry_time": r.entry_time, "exit": r.exit,
                     "r_net": r.r_net, "risk_pts": r.risk_pts})
for mode in ("prev_1h_candle", "4h_extreme", *stops_ext.KINDS):
    B.STOP_MODE = mode
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run()
    t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
    name = {"prev_1h_candle": "prev 1H candle (current)", "4h_extreme": "4H extreme"}.get(mode, mode)
    for r in t.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "variant": name, "model": "intraday", "entry_time": r.entry_time,
                     "exit": r.exit, "r_net": r.r_net, "risk_pts": r.risk_pts})
    print("done", mode, flush=True)
pd.DataFrame(rows).to_csv(f"output/stop2_{S.DATA_SOURCE}.csv", index=False)
