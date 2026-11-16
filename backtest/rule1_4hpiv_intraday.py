"""Robustness: intraday with 4H(N)/D/W/M liquidity for N = 8, 12."""
import contextlib, io
import pandas as pd
import backtest as B, ifvg, swings as S
B.plot_trade = lambda *a, **k: None
rows = []
ifvg.SWEEP_TFS = ("M", "W", "D", "4H")
for piv in (8, 12):
    S.PIVOT_BY_TF = {**S.PIVOT_BY_TF, "4H": piv}
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run()
    t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
    for r in t.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "variant": f"4H({piv})/D/W/M", "model": "intraday", "entry_time": r.entry_time, "exit": r.exit, "r_net": r.r_net})
pd.DataFrame(rows).to_csv(f"output/r1_4hpiv2_{S.DATA_SOURCE}.csv", index=False)
