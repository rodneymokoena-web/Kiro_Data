"""M1 rule 3 with the current Rule 2 (last FVG, any sweeping leg) vs the previous Rule 2 (first inverted FVG, leg from
the last 4H swing, formed into the sweep) - the TradingView scripts' current-rule path still uses the previous Rule 2."""
import contextlib, io
import pandas as pd
import backtest as B, ifvg, swing as W, swings as S
B.plot_trade = lambda *a, **k: None
W.plot_trade = lambda *a, **k: None
rows = []
for name, (sel, leg) in {"R2 last FVG any leg": ("last", "any"), "R2 previous (first FVG, 4H swing leg)": ("first", "swing")}.items():
    ifvg.FVG_SELECT, ifvg.LEG_MODE = sel, leg
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run(); w, _ = W.run()
    t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
    w = w[(w.entry_type == "1H touch") & (w.stop_type == "4H extreme") & (w.target_type == "3R")]
    for model, df in (("intraday 5m touch", t), ("swing 1H touch", w)):
        for r in df.itertuples(index=False):
            rows.append({"source": S.DATA_SOURCE, "variant": name, "model": model, "entry_time": r.entry_time, "exit": r.exit, "r_net": r.r_net})
pd.DataFrame(rows).to_csv(f"output/r2m1_{S.DATA_SOURCE}.csv", index=False)
