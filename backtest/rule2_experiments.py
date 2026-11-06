"""Rule 2 comparison (sweep levels, leg start, FVG formed into the sweep), both strategies.

Usage:
    DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule2_experiments.py
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

VARIANTS = {   # SWEEP_TFS, LEG_MODE, FVG_INTO_SWEEP
    "OLD  D/W/M levels, leg = lowest of 20, any FVG": (("M", "W", "D"), "lookback", False),
    "D equal H/L, leg = last 4H swing, FVG into sweep": (("D",), "swing", True),
    "D equal H/L, leg = lowest of 20, FVG into sweep": (("D",), "lookback", True),
}


def funnel() -> dict:
    out = {}
    for sym, (f1, _, _) in S.SYMBOLS.items():
        h1 = S.load(S.DATA / f1)
        _, st = ifvg_1h.build_4h_setups(h1)
        fv = ifvg.find_fvgs(h1)
        sig = [x for x in st if ifvg_1h.find_1h_ifvg(x, h1, fv)["status"] == "signal"]
        out[sym] = f"{len(st)} 4H -> {len(sig)} 1H"
    return out


def main() -> None:
    saved = (ifvg.SWEEP_TFS, ifvg.LEG_MODE, ifvg.FVG_INTO_SWEEP)
    rows = []
    for name, (tfs, leg, into) in VARIANTS.items():
        ifvg.SWEEP_TFS, ifvg.LEG_MODE, ifvg.FVG_INTO_SWEEP = tfs, leg, into
        fn = funnel()
        with contextlib.redirect_stdout(io.StringIO()):
            t = B.run()
            w, _ = W.run()
        w = w[(w.target_type == "3R")]
        groups = [("intraday", t[(t.entry_tf == "5m") & (t.entry_mode == m)], f"5m {m}") for m in ("touch", "ce")]
        groups += [(f"swing {st_}", w[(w.stop_type == st_) & (w.entry_type == e)], e)
                   for st_ in ("4H extreme", "prev 4H candle") for e in ("1H touch", "1H CE")]
        for strat, g, entry in groups:
            for sym in ["US100", "XAUUSD", "ALL"]:
                x = g if sym == "ALL" else g[g.symbol == sym]
                rows.append({"source": S.DATA_SOURCE, "variant": name, "strategy": strat, "entry": entry,
                             "symbol": sym, "funnel": fn.get(sym, ""), **stats(x)})
        print("done:", name, fn, flush=True)
    ifvg.SWEEP_TFS, ifvg.LEG_MODE, ifvg.FVG_INTO_SWEEP = saved
    df = pd.DataFrame(rows)
    df.to_csv(f"output/rule2_{S.DATA_SOURCE}.csv", index=False)


if __name__ == "__main__":
    main()
