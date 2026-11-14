import contextlib, io, sys
import pandas as pd
import backtest as B, ifvg, swing as W, swings as S
from rule1_experiments import stats
VARIANTS = {"A  original rule 1 + 4H swing leg + FVG into sweep (new default)": ("swing", True),
            "B  original rule 1 + original rule 2 (lowest/highest of 20, any FVG)": ("lookback", False)}
rows = []
saved = (ifvg.LEG_MODE, ifvg.FVG_INTO_SWEEP)
for name, (leg, into) in VARIANTS.items():
    ifvg.LEG_MODE, ifvg.FVG_INTO_SWEEP = leg, into
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run(); w, _ = W.run()
    w = w[w.target_type == "3R"]
    groups = [("intraday", t[(t.entry_tf == "5m") & (t.entry_mode == m)], f"5m {m}") for m in ("touch", "ce")]
    groups += [(f"swing {s_}", w[(w.stop_type == s_) & (w.entry_type == e)], e) for s_ in ("4H extreme", "prev 4H candle") for e in ("1H touch", "1H CE")]
    for strat, g, entry in groups:
        for sym in ["US100", "XAUUSD", "ALL"]:
            x = g if sym == "ALL" else g[g.symbol == sym]
            rows.append({"source": S.DATA_SOURCE, "variant": name, "strategy": strat, "entry": entry, "symbol": sym, **stats(x)})
ifvg.LEG_MODE, ifvg.FVG_INTO_SWEEP = saved
pd.DataFrame(rows).to_csv(f"output/revert1_{S.DATA_SOURCE}.csv", index=False)
