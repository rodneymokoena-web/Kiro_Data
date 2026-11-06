"""Rule 3 comparison: 1H FVG inversion with displacement + MSS (v2 pipeline) per leg mode, vs previous rules (v1).

Usage:
    DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule3_experiments.py
"""
import contextlib
import io

import pandas as pd

import backtest as B
import ifvg
import ifvg_1h
import swing as W
import swings as S
from rule1_experiments import stats

VARIANTS = {   # pipeline, leg mode
    "PREVIOUS rules (4H IFVG -> retest -> 1H IFVG), leg = last 4H swing": ("v1", "swing"),
    "NEW rule 3, leg = last 4H swing": ("v2", "swing"),
    "NEW rule 3, leg = lowest/highest of 20": ("v2", "lookback"),
}


def main() -> None:
    saved = (ifvg_1h.PIPELINE, ifvg.LEG_MODE)
    rows = []
    for name, (pipe, leg) in VARIANTS.items():
        ifvg_1h.PIPELINE, ifvg.LEG_MODE = pipe, leg
        with contextlib.redirect_stdout(io.StringIO()):
            t = B.run()
            w, _ = W.run()
        w = w[(w.target_type == "3R")]
        groups = [("intraday", t[(t.entry_tf == "5m") & (t.entry_mode == m)] if len(t) else t, f"5m {m}") for m in ("touch", "ce")]
        groups += [(f"swing {st_}", w[(w.stop_type == st_) & (w.entry_type == e)] if len(w) else w, e)
                   for st_ in ("4H extreme", "prev 4H candle") for e in ("1H touch", "1H CE")]
        for strat, g, entry in groups:
            for sym in ["US100", "XAUUSD", "ALL"]:
                x = g if sym == "ALL" or g.empty else g[g.symbol == sym]
                rows.append({"source": S.DATA_SOURCE, "variant": name, "strategy": strat, "entry": entry,
                             "symbol": sym, **stats(x)})
        print("done:", name, flush=True)
    ifvg_1h.PIPELINE, ifvg.LEG_MODE = saved
    pd.DataFrame(rows).to_csv(f"output/rule3_{S.DATA_SOURCE}.csv", index=False)


if __name__ == "__main__":
    main()
