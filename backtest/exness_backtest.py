"""Full backtest on Exness USTEC: signals from Exness candles (built from ticks), fills/exits replayed on Exness ticks.

Usage:
    DATA_SOURCE=exness TEST_START=2021-04-01 [TRADE_SYMBOLS=XAUUSD] .venv/bin/python exness_backtest.py
Both models with the current default rules (swing = swing_snap.py, intraday = backtest.py, 4H(10)/D/W/M liquidity).
Writes output/exness_trades.csv (candle + tick result per trade), output/exness_summary.csv,
       output/exness_capital_by_year.csv, output/exness_monthly_1pct.csv.
"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path

import numpy as np
import pandas as pd

import backtest as B
import make_us100_results as M
import swing_snap as SN
import swings as S
import tick_backtest as T

HERE = Path(__file__).parent
OUT = HERE / "output"
DATA_END = pd.Timestamp("2026-10-29", tz="UTC")
assert S.DATA_SOURCE == "exness", "run with DATA_SOURCE=exness"
SYMBOL = S.TRADE_SYMBOLS[0]                                  # US100 | XAUUSD
T.TICK_SYMBOL = {"US100": "USTEC", "XAUUSD": "XAUUSD"}[SYMBOL]
SUFFIX = "" if SYMBOL == "US100" else f"_{SYMBOL.lower()}"


def main() -> None:
    B.plot_trade = lambda *a, **k: None
    sw = SN.run()
    with contextlib.redirect_stdout(io.StringIO()):
        it = B.run()
    it = it[(it.entry_tf == "5m") & (it.entry_mode == "touch")].rename(columns={"entry_price": "entry"})
    m1 = S.load(HERE / "data" / "exness" / f"{SYMBOL}_1m.csv")
    rows = []
    for model, d in (("swing", sw), ("intraday", it)):
        for tr in d.sort_values("entry_time").to_dict("records"):
            res = T.sim(tr, model, m1, DATA_END, fixed_offset=0.0)
            rows.append({"model": model, "entry_time": tr["entry_time"], "signal": tr["signal"], "entry": tr["entry"],
                         "stop": tr["stop"], "target": tr["target"], "risk_pts": tr["risk_pts"],
                         "candle_exit": tr["exit"], "candle_r": tr["r_net"], **res})
        print("done", model, len(d), flush=True)
    t = pd.DataFrame(rows)
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    t["period"] = np.where(t["entry_time"] < pd.Timestamp("2024-01-01", tz="UTC"), "2021-23", "2024-26")
    t.to_csv(OUT / f"exness_trades{SUFFIX}.csv", index=False)

    ok = t[t.tick_status == "ok"].sort_values("entry_time")
    summ = []
    for label, g_all in (("swing", t[t.model == "swing"]), ("intraday", t[t.model == "intraday"]), ("both (1% each)", t)):
        g = ok[ok.index.isin(g_all.index)]
        for per in ("2021-26", "2021-23", "2024-26"):
            gp = g if per == "2021-26" else g[g.period == per]
            for basis, col in (("ticks", "tick_r"), ("candles", "candle_r")):
                st = M.stats(gp[col])
                summ.append({"model": label, "period": per, "basis": basis, "trades": st["trades"],
                             "W/L/BE": f'{st["W"]}/{st["L"]}/{st["BE"]}',
                             "win%": round(100 * st["W"] / max(st["trades"], 1)), "PF": st["PF"], "R": st["R"],
                             "capital": st["account"], "return%": round((st["account"] / 10000 - 1) * 100, 1),
                             "maxDD%": st["maxDD%"]})
    s = pd.DataFrame(summ)
    s.to_csv(OUT / f"exness_summary{SUFFIX}.csv", index=False)

    # year-end capital (ticks), compounding from $10k, 1% risk
    yrows = []
    for label, g in (("swing", ok[ok.model == "swing"]), ("intraday", ok[ok.model == "intraday"]), ("both", ok)):
        eq = peak = 10000.0
        for y in range(2021, 2027):
            gy = g[g.entry_time.dt.year == y]
            start, dd = eq, 0.0
            for r in gy.tick_r:
                eq *= 1 + 0.01 * r
                peak = max(peak, eq)
                dd = max(dd, (peak - eq) / peak)
            yrows.append({"model": label, "year": y, "trades": len(gy), "R": round(gy.tick_r.sum(), 1),
                          "end capital": round(eq), "year %": round((eq / start - 1) * 100, 1), "maxDD%": round(dd * 100, 1)})
    pd.DataFrame(yrows).to_csv(OUT / f"exness_capital_by_year{SUFFIX}.csv", index=False)

    # monthly reset ($10k each month, 1% risk, both models, ticks)
    ok2 = ok.assign(month=ok.entry_time.dt.tz_convert(None).dt.to_period("M"))
    mrows = []
    for mo in pd.period_range("2021-04", "2026-10", freq="M"):
        gm = ok2[ok2.month == mo]
        eq = peak = 10000.0
        dd = 0.0
        for r in gm.tick_r:
            eq *= 1 + 0.01 * r
            peak = max(peak, eq)
            dd = max(dd, (peak - eq) / peak)
        mrows.append({"month": str(mo), "trades": len(gm), "profit": round(eq - 10000), "ret%": round((eq / 10000 - 1) * 100, 2),
                      "maxDD%": round(dd * 100, 2)})
    pd.DataFrame(mrows).to_csv(OUT / f"exness_monthly_1pct{SUFFIX}.csv", index=False)

    pd.set_option("display.width", 250)
    print(t.tick_status.value_counts().to_string())
    print(s.to_string(index=False))
    print(pd.DataFrame(yrows).to_string(index=False))


if __name__ == "__main__":
    main()
