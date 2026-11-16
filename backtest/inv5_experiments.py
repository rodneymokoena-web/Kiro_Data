import contextlib, io, os
import backtest as B, swings as S
B.plot_trade = lambda *a, **k: None
with contextlib.redirect_stdout(io.StringIO()):
    t = B.run()
t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
v = os.environ["VARIANT"]
t.assign(source=S.DATA_SOURCE)[["source", "entry_time", "exit", "r_net", "risk_pts"]].to_csv(f"output/inv5_{S.DATA_SOURCE}_{v}.csv", index=False)
print("done", S.DATA_SOURCE, v, len(t))
