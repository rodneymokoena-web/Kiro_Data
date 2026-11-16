"""Rule 4 with vs without the cancellation (price beyond the sweep extreme before the retest).
Usage:  DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule4_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, ifvg_1h, swing as W, swings as S
B.plot_trade = lambda *a, **k: None
W.plot_trade = lambda *a, **k: None
rows = []
for name, cancel in (("C current: cancel beyond sweep extreme", True), ("N no cancellation, extreme follows price", False)):
    ifvg_1h.RETEST_CANCEL = cancel
    for r3 in ("4H close", "M6"):
        W.RULE3 = r3
        with contextlib.redirect_stdout(io.StringIO()):
            w, _ = W.run()
            t = B.run() if r3 == "4H close" else None
        w = w[(w.entry_type == "1H touch") & (w.stop_type == "4H extreme") & (w.target_type == "3R")]
        out = [("swing" if r3 == "4H close" else "swing M6", w)]
        if t is not None:
            out.append(("intraday", t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]))
        for model, df in out:
            for r in df.itertuples(index=False):
                rows.append({"source": S.DATA_SOURCE, "variant": name, "model": model, "entry_time": r.entry_time,
                             "exit": r.exit, "r_net": r.r_net})
    print("done", name, flush=True)
ifvg_1h.RETEST_CANCEL = True
pd.DataFrame(rows).to_csv(f"output/rule4_{S.DATA_SOURCE}.csv", index=False)
