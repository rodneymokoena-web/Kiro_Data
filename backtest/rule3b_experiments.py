"""Revised rule 3: 4H FVG inverted by a 1H close (1H displacement + 1H MSS, 4H CISD) vs the current 4H inversion.
Usage:  DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule3b_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, ifvg, ifvg_1h, setups_v3 as V3, swing as W, swings as S
B.plot_trade = lambda *a, **k: None
W.plot_trade = lambda *a, **k: None
VARIANTS = {   # PIPELINE, CISD_MODE, REQUIRE, WAIT_1H
    "A current: 4H close inverts, 4H disp + 4H CISD/MSS": ("v1", None, None, 0),
    "B 1H inversion, CISD on 4H close OR 1H MSS (strict)": ("v3", "4h_close", "or", 0),
    "C 1H inversion, CISD on 4H close AND 1H MSS (strict)": ("v3", "4h_close", "and", 0),
    "D 1H inversion, CISD 4H close OR 1H MSS, may confirm up to 8 1H later": ("v3", "4h_close", "or", 8),
    "E 1H inversion, 4H CISD level broken by 1H close OR 1H MSS": ("v3", "1h_close", "or", 0),
    "F 1H inversion, 4H CISD level broken by 1H close AND 1H MSS": ("v3", "1h_close", "and", 0),
}
rows, saved = [], (ifvg_1h.PIPELINE, V3.CISD_MODE, V3.REQUIRE, V3.WAIT_1H)
for name, (pl, cm, rq, wt) in VARIANTS.items():
    ifvg_1h.PIPELINE = pl
    if pl == "v3":
        V3.CISD_MODE, V3.REQUIRE, V3.WAIT_1H = cm, rq, wt
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
ifvg_1h.PIPELINE, V3.CISD_MODE, V3.REQUIRE, V3.WAIT_1H = saved
pd.DataFrame(rows).to_csv(f"output/rule3b_{S.DATA_SOURCE}.csv", index=False)
