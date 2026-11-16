"""Ways to shorten the hold time of the intraday model (5m touch), tested on GoatFunded and Pepperstone.

Usage:
    TEST_START=2024-01-01 .venv/bin/python hold_experiments.py

Uses the trades already found by backtest.py for each broker (output_goat/, output_pepperstone/) and
re-simulates them on 5m candles. Breakeven at +1R stays on in every variant.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

import swings
from backtest import SL_BUFFER
from stop_experiments import atr
from swings import build_htf, load

VARIANTS = {
    "BASE (4H stop, 3R)":                 dict(),
    "cap stop 1.5 x ATR(D)":              dict(cap_k=1.5),
    "cap stop 1.0 x ATR(D)":              dict(cap_k=1.0),
    "target 2.5R":                        dict(tgt=2.5),
    "target 2R":                          dict(tgt=2.0),
    "time stop 20 days":                  dict(max_days=20),
    "time stop 10 days":                  dict(max_days=10),
    "50% off at 1.5R, rest 3R":           dict(partial=1.5),
    "cap 1.5 x ATR(D) + target 2.5R":     dict(cap_k=1.5, tgt=2.5),
}


def sim(b: pd.DataFrame, q: int, short: bool, entry: float, sl: float, tgt: float, max_days, partial):
    h, l, c, idx = b["High"].to_numpy(), b["Low"].to_numpy(), b["Close"].to_numpy(), b.index
    risk = abs(entry - sl)
    tp = entry - tgt * risk if short else entry + tgt * risk
    stop, be, half_done, booked = sl, False, False, 0.0
    t_end = idx[q] + pd.Timedelta(days=max_days) if max_days else None
    w = 1.0                                                            # open position fraction
    for k in range(q, len(b)):
        if t_end is not None and idx[k] >= t_end:
            px = c[k - 1]
            return booked + w * ((entry - px) if short else (px - entry)), "time", idx[k]
        if (h[k] >= stop) if short else (l[k] <= stop):
            return booked + w * ((entry - stop) if short else (stop - entry)), ("breakeven" if be else "stop"), idx[k]
        if k > q:
            if partial and not half_done:
                p = entry - partial * risk if short else entry + partial * risk
                if (l[k] <= p) if short else (h[k] >= p):
                    booked += 0.5 * partial * risk
                    w, half_done = 0.5, True
            if (l[k] <= tp) if short else (h[k] >= tp):
                return booked + w * tgt * risk, "target", idx[k]
            fav = (entry - l[k]) if short else (h[k] - entry)
            if not be and fav >= risk:
                stop, be = entry, True
    px = c[-1]
    return booked + w * ((entry - px) if short else (px - entry)), "open", idx[-1]


def main() -> None:
    pd.set_option("display.width", 250)
    rows = []
    for src in ("goat", "pepperstone"):
        data_dir, files = swings._SOURCES[src]
        cost = pd.read_json(data_dir / "costs.json", typ="series").to_dict()
        t = pd.read_csv(f"output_{src}/backtest/trades.csv", parse_dates=["entry_time"])
        t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")]
        bars, aD = {}, {}
        for sym, (f1, _, f5) in files.items():
            h1 = load(data_dir / f1)
            d = build_htf(h1, "D")
            aD[sym] = atr(d).shift(1).set_axis(pd.DatetimeIndex(d["End"]))
            bars[sym] = load(data_dir / f5)
        for name, v in VARIANTS.items():
            res = []
            for tr in t.itertuples(index=False):
                sym, short = tr.symbol, tr.signal == "short"
                entry, sl = tr.entry_price, tr.stop
                risk = abs(entry - sl)
                if v.get("cap_k") and risk > v["cap_k"] * aD[sym].asof(tr.entry_time):
                    risk = v["cap_k"] * aD[sym].asof(tr.entry_time)
                    sl = entry + risk if short else entry - risk
                q = bars[sym].index.searchsorted(tr.entry_time)
                pnl, ex, t_exit = sim(bars[sym], q, short, entry, sl, v.get("tgt", 3.0), v.get("max_days"), v.get("partial"))
                res.append({"symbol": sym, "entry_time": tr.entry_time, "exit": ex, "r": (pnl - cost[sym]) / risk,
                            "days": (t_exit - tr.entry_time).total_seconds() / 86400})
            res = pd.DataFrame(res)
            for sym in ["US100", "XAUUSD", "ALL"]:
                g = res if sym == "ALL" else res[res.symbol == sym]
                win, loss = g.r[g.r > 0].sum(), abs(g.r[g.r < 0].sum())
                eq, peak, dd = 10_000.0, 10_000.0, 0.0
                for r in g.sort_values("entry_time").r:
                    eq += eq * 0.01 * r; peak = max(peak, eq); dd = max(dd, (peak - eq) / peak * 100)
                rows.append({"broker": src, "variant": name, "symbol": sym, "trades": len(g),
                             "win%": round(100 * (g.r > 0.05).mean(), 1), "PF": round(win / loss, 2) if loss else float("inf"),
                             "R": round(g.r.sum(), 2), "account": int(round(eq)), "maxDD%": round(dd, 1),
                             "avg_days": round(g.days.mean(), 1), "median_days": round(g.days.median(), 1),
                             "max_days": round(g.days.max(), 1)})
    df = pd.DataFrame(rows)
    df.to_csv("output/hold_experiments.csv", index=False)
    print(df[df.symbol == "ALL"].to_string(index=False))
    print()
    print(df[df.symbol != "ALL"].to_string(index=False))


if __name__ == "__main__":
    main()
