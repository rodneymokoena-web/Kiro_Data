"""Rule 3 inversion by a 1H WICK below the 4H FVG, by where that candle closes: (a) below, (b) inside, (c) above.
Usage:  DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule3c_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, ifvg, ifvg_1h, setups_v3 as V3, swing as W, swings as S
B.plot_trade = lambda *a, **k: None
W.plot_trade = lambda *a, **k: None
OR_ = ("4h_close", "or")          # CISD on a 4H close OR 1H MSS (literal rule)
AND_ = ("1h_close", "and")        # 4H CISD level broken by a 1H close AND 1H MSS (best 1H version so far, "F")
VARIANTS = {   # PIPELINE, INVERT_ON, WICK_CLOSE, (CISD_MODE, REQUIRE)
    "A current: 4H close inverts": ("v1", None, None, None),
    "B 1H close inverts, CISD4H or MSS1H": ("v3", "close", "any", OR_),
    "F 1H close inverts, CISD lvl 1H close and MSS1H": ("v3", "close", "any", AND_),
    "Ga wick, close BELOW FVG, CISD4H or MSS1H": ("v3", "wick", "through", OR_),
    "Gb wick, close INSIDE FVG, CISD4H or MSS1H": ("v3", "wick", "inside", OR_),
    "Gc wick, close ABOVE FVG, CISD4H or MSS1H": ("v3", "wick", "back", OR_),
    "Gd wick, any close, CISD4H or MSS1H": ("v3", "wick", "any", OR_),
    "Ha wick, close BELOW FVG, CISD lvl and MSS1H": ("v3", "wick", "through", AND_),
    "Hb wick, close INSIDE FVG, CISD lvl and MSS1H": ("v3", "wick", "inside", AND_),
    "Hc wick, close ABOVE FVG, CISD lvl and MSS1H": ("v3", "wick", "back", AND_),
    "Hd wick, any close, CISD lvl and MSS1H": ("v3", "wick", "any", AND_),
}
saved = (ifvg_1h.PIPELINE, V3.INVERT_ON, V3.WICK_CLOSE, V3.CISD_MODE, V3.REQUIRE)
rows = []
for name, (pl, inv, wc, conf) in VARIANTS.items():
    ifvg_1h.PIPELINE = pl
    if pl == "v3":
        V3.INVERT_ON, V3.WICK_CLOSE, (V3.CISD_MODE, V3.REQUIRE) = inv, wc, conf
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
ifvg_1h.PIPELINE, V3.INVERT_ON, V3.WICK_CLOSE, V3.CISD_MODE, V3.REQUIRE = saved
pd.DataFrame(rows).to_csv(f"output/rule3c_{S.DATA_SOURCE}.csv", index=False)
