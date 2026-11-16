"""Rule 1 liquidity: 4H swings with a larger pivot (5 / 10 candles each side) + D/W/M, both models.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule1_4hpiv_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, ifvg, swing_snap as SN, swings as S
B.plot_trade = lambda *a, **k: None
rows = []
ifvg.SWEEP_TFS = ("M", "W", "D", "4H")
for piv in (5, 10):
    S.PIVOT_BY_TF = {**S.PIVOT_BY_TF, "4H": piv}
    name = f"4H({piv})/D/W/M"
    sw = SN.run()
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run()
    t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
    for model, df in (("swing", sw), ("intraday", t)):
        for r in df.itertuples(index=False):
            rows.append({"source": S.DATA_SOURCE, "variant": name, "model": model, "entry_time": r.entry_time,
                         "exit": r.exit, "r_net": r.r_net})
    print("done", name, len(sw), len(t), flush=True)
pd.DataFrame(rows).to_csv(f"output/r1_4hpiv_{S.DATA_SOURCE}.csv", index=False)
