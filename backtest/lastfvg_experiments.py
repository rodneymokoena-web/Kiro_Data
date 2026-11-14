"""Rule 2 FVG selection: OLD (first inverted FVG formed into the sweep) vs NEW (last FVG of the sweeping leg).
Usage:  DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python lastfvg_experiments.py
"""
import contextlib, io
import pandas as pd
import backtest as B, ifvg, ifvg_1h, swing as W, swings as S
B.plot_trade = lambda *a, **k: None
W.plot_trade = lambda *a, **k: None
VARIANTS = {"OLD first inverted FVG, formed into sweep": ("first", True), "NEW last FVG of the leg (swing low -> sweep)": ("last", True)}
rows, saved = [], (ifvg.FVG_SELECT, ifvg.FVG_INTO_SWEEP)
for name, (sel, into) in VARIANTS.items():
    ifvg.FVG_SELECT, ifvg.FVG_INTO_SWEEP = sel, into
    nset = {}
    for sym, (f1, _, _) in S.SYMBOLS.items():
        h1 = S.load(S.DATA / f1); _, st = ifvg_1h.build_4h_setups(h1); fv = ifvg.find_fvgs(h1)
        nset[sym] = (len(st), sum(ifvg_1h.find_1h_ifvg(x, h1, fv)["status"] == "signal" for x in st))
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run(); w, _ = W.run()
    t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")] if len(t) else t
    w = w[(w.entry_type == "1H touch") & (w.stop_type == "4H extreme") & (w.target_type == "3R")] if len(w) else w
    for model, df in (("intraday 5m touch", t), ("swing 1H touch", w)):
        for r in df.itertuples(index=False):
            rows.append({"source": S.DATA_SOURCE, "variant": name, "model": model, "entry_time": r.entry_time,
                         "exit": r.exit, "r_net": r.r_net, "setups4h": nset["US100"][0], "signals1h": nset["US100"][1]})
    print("done", name, nset, flush=True)
ifvg.FVG_SELECT, ifvg.FVG_INTO_SWEEP = saved
pd.DataFrame(rows).to_csv(f"output/lastfvg_{S.DATA_SOURCE}.csv", index=False)
