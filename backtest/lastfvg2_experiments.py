"""Rule 2: last FVG of ANY leg sweeping the D/W/M level (lookback caps) vs last FVG from the last 4H swing vs previous rule.
Usage:  DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python lastfvg2_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, ifvg, ifvg_1h, swing as W, swings as S
B.plot_trade = lambda *a, **k: None
W.plot_trade = lambda *a, **k: None
VARIANTS = {   # FVG_SELECT, LEG_MODE, LEG_MAX_LOOKBACK
    "A previous rule: first inverted FVG, leg from last 4H swing": ("first", "swing", 60),
    "B last FVG, leg from last 4H swing -> sweep": ("last", "swing", 60),
    "C last FVG, any sweeping leg, within 20 4H candles": ("last", "any", 20),
    "D last FVG, any sweeping leg, within 40 4H candles": ("last", "any", 40),
    "E last FVG, any sweeping leg, within 60 4H candles": ("last", "any", 60),
    "F last FVG, any sweeping leg, no limit": ("last", "any", 100000),
}
rows, saved = [], (ifvg.FVG_SELECT, ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK)
for name, (sel, leg, lb) in VARIANTS.items():
    ifvg.FVG_SELECT, ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK = sel, leg, lb
    h1 = S.load(S.DATA / S.SYMBOLS["US100"][0]); _, st = ifvg_1h.build_4h_setups(h1); fv = ifvg.find_fvgs(h1)
    n4, n1 = len(st), sum(ifvg_1h.find_1h_ifvg(x, h1, fv)["status"] == "signal" for x in st)
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run(); w, _ = W.run()
    t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")] if len(t) else t
    w = w[(w.entry_type == "1H touch") & (w.stop_type == "4H extreme") & (w.target_type == "3R")] if len(w) else w
    for model, df in (("intraday 5m touch", t), ("swing 1H touch", w)):
        for r in df.itertuples(index=False):
            rows.append({"source": S.DATA_SOURCE, "variant": name, "model": model, "entry_time": r.entry_time,
                         "exit": r.exit, "r_net": r.r_net, "setups4h": n4, "signals1h": n1})
    print("done", name, n4, n1, flush=True)
ifvg.FVG_SELECT, ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK = saved
pd.DataFrame(rows).to_csv(f"output/lastfvg2_{S.DATA_SOURCE}.csv", index=False)
