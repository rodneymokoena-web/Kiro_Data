"""Rule 1 comparison: D swing definition (old 2/2 all swings vs 1/1 relative equal highs/lows).

Usage:
    DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python rule1_experiments.py

Runs the intraday backtest (5m touch / 5m CE, current rule 6-7) and the swing backtest (1H touch / 1H CE)
for each variant and writes output/rule1_{source}.csv. Leaves swings.py settings unchanged afterwards.
"""
import contextlib
import io

import numpy as np
import pandas as pd

import backtest as B
import swing as W
import swings as S

VARIANTS = {
    "OLD  D 2/2 all swings":       ({}, False, 0.2),
    "D 1/1 all swings":            ({"D": 1}, False, 0.2),
    "D 1/1 equal H/L tol 0.1 ATR": ({"D": 1}, True, 0.1),
    "NEW  D 1/1 equal H/L tol 0.2 ATR": ({"D": 1}, True, 0.2),
    "D 1/1 equal H/L tol 0.3 ATR": ({"D": 1}, True, 0.3),
}


def stats(g: pd.DataFrame) -> dict:
    if g.empty:
        return {"trades": 0}
    win, loss = g.r_net[g.r_net > 0].sum(), abs(g.r_net[g.r_net < 0].sum())
    eq, peak, dd = 10_000.0, 10_000.0, 0.0
    for r in g.sort_values("entry_time").r_net:
        eq += eq * 0.01 * r; peak = max(peak, eq); dd = max(dd, (peak - eq) / peak * 100)
    return {"trades": len(g), "W": int((g.exit == "target").sum()), "L": int((g.exit == "stop").sum()),
            "BE": int((g.exit == "breakeven").sum()), "PF": round(win / loss, 2) if loss else float("inf"),
            "R": round(g.r_net.sum(), 2), "account": int(round(eq)), "maxDD%": round(dd, 1)}


def main() -> None:
    saved = (S.PIVOT_BY_TF, S.D_EQUAL_ONLY, S.EQ_TOL_ATR)
    rows = []
    for name, (pv, eq, tol) in VARIANTS.items():
        S.PIVOT_BY_TF, S.D_EQUAL_ONLY, S.EQ_TOL_ATR = pv, eq, tol
        with contextlib.redirect_stdout(io.StringIO()):
            t = B.run()
            w, _ = W.run()
        w = w.rename(columns={"entry_type": "entry_mode"})
        for strat, df, filters in (("intraday", t, [("5m", "touch"), ("5m", "ce")]),
                                   ("swing 4H-extreme stop", w[w.stop_type == "4H extreme"], [("1H", "1H touch"), ("1H", "1H CE")]),
                                   ("swing prev-4H-candle stop", w[w.stop_type == "prev 4H candle"], [("1H", "1H touch"), ("1H", "1H CE")])):
            if strat.startswith("swing"):
                df = df[df.target_type == "3R"]
            for tf, mode in filters:
                g = df[(df.entry_mode == mode)] if strat.startswith("swing") else df[(df.entry_tf == tf) & (df.entry_mode == mode)]
                for sym in ["US100", "XAUUSD", "ALL"]:
                    x = g if sym == "ALL" else g[g.symbol == sym]
                    rows.append({"source": S.DATA_SOURCE, "variant": name, "strategy": strat,
                                 "entry": f"{tf} {mode}".replace("1H 1H", "1H"), "symbol": sym, **stats(x)})
        print("done:", name, flush=True)
    S.PIVOT_BY_TF, S.D_EQUAL_ONLY, S.EQ_TOL_ATR = saved
    df = pd.DataFrame(rows)
    df.to_csv(f"output/rule1_{S.DATA_SOURCE}.csv", index=False)
    pd.set_option("display.width", 250)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
