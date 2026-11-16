"""Swing: current rule 3 vs the optional Ha (causal FVG choice). Writes output/rule3ha_{source}.csv"""
import contextlib, io, sys
import pandas as pd
import swing as W, swings as S
W.plot_trade = lambda *a, **k: None
rows = []
for r3 in ("4H close", "Ha"):
    W.RULE3 = r3
    with contextlib.redirect_stdout(io.StringIO()):
        w, _ = W.run()
    w = w[(w.entry_type == "1H touch") & (w.stop_type == "4H extreme") & (w.target_type == "3R")]
    w = w.assign(source=S.DATA_SOURCE, variant=r3, model="swing 1H touch")
    rows.append(w)
pd.concat(rows).to_csv(f"output/rule3ha_{S.DATA_SOURCE}.csv", index=False)
print("done", S.DATA_SOURCE)
