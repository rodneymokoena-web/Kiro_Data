import contextlib, io, os
import backtest as B, swings as S
B.plot_trade = lambda *a, **k: None
with contextlib.redirect_stdout(io.StringIO()):
    t = B.run()
v = os.environ.get("VARIANT", "R")
t.assign(source=S.DATA_SOURCE).to_csv(f"output/snap_{S.DATA_SOURCE}_{v}.csv", index=False)
print("done", S.DATA_SOURCE, v, len(t))
