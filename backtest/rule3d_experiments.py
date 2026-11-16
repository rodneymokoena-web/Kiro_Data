"""Rule 3 without the 4H CISD: only a 1H MSS (previous 1H swing low, before or after the sweep) confirms the inversion.
Usage:  DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule3d_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, ifvg, ifvg_1h, setups_v3 as V3, swing as W, swings as S
B.plot_trade = lambda *a, **k: None
W.plot_trade = lambda *a, **k: None
VARIANTS = {   # pipeline, CONFIRM_4H / (INVERT_ON, WICK_CLOSE, CISD_MODE, REQUIRE), MSS mode
    "A previous: 4H close, 4H disp + 4H CISD/MSS": ("v1", "CISD or MSS", "ext"),
    "Ha option: 1H wick+close, 1H disp + 4H CISD + 1H MSS": ("v3", ("wick", "through", "1h_close", "and"), "ext"),
    "M1 4H close, 4H disp + 1H MSS (swing before extreme)": ("v1", "1H MSS", "ext"),
    "M2 4H close, 4H disp + 1H MSS (latest swing, before/after sweep)": ("v1", "1H MSS", "any"),
    "M3 1H close, 1H disp + 1H MSS (swing before extreme)": ("v3", ("close", "any", "1h_close", "mss"), "ext"),
    "M4 1H close, 1H disp + 1H MSS (latest swing, before/after sweep)": ("v3", ("close", "any", "1h_close", "mss"), "any"),
    "M5 1H wick+close, 1H disp + 1H MSS (swing before extreme)": ("v3", ("wick", "through", "1h_close", "mss"), "ext"),
    "M6 1H wick+close, 1H disp + 1H MSS (latest swing, before/after sweep)": ("v3", ("wick", "through", "1h_close", "mss"), "any"),
}
saved = (ifvg_1h.PIPELINE, ifvg_1h.CONFIRM_4H, ifvg_1h.MSS_MODE_1H, V3.INVERT_ON, V3.WICK_CLOSE, V3.CISD_MODE, V3.REQUIRE, V3.MSS_MODE)
rows = []
for name, (pl, conf, mm) in VARIANTS.items():
    ifvg_1h.PIPELINE = pl
    if pl == "v1":
        ifvg_1h.CONFIRM_4H, ifvg_1h.MSS_MODE_1H = conf, mm
    else:
        (V3.INVERT_ON, V3.WICK_CLOSE, V3.CISD_MODE, V3.REQUIRE), V3.MSS_MODE = conf, mm
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
    (ifvg_1h.PIPELINE, ifvg_1h.CONFIRM_4H, ifvg_1h.MSS_MODE_1H, V3.INVERT_ON, V3.WICK_CLOSE, V3.CISD_MODE, V3.REQUIRE,
     V3.MSS_MODE) = saved
pd.DataFrame(rows).to_csv(f"output/rule3d_{S.DATA_SOURCE}.csv", index=False)
