"""Stop-loss experiments for both strategies (intraday 5m touch and swing main), 2024-2026.

Usage:
    TEST_START=2024-01-01 .venv/bin/python stop_experiments.py

Re-simulates the trades already found by backtest.py / swing.py (same setups, entries and fill times)
with different stop rules. Target is always 3R of the (new) risk; breakeven at +1R unless noted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest import COST, SL_BUFFER
from swings import DATA, SYMBOLS, build_htf, load

VARIANTS = {
    "BASE  4H extreme + fixed buffer":        dict(buf="fixed"),
    "A  4H extreme + 0.5 x ATR(1H) buffer":   dict(buf="atr"),
    "B  skip if stop > 1.5 x ATR(D)":         dict(buf="fixed", skip_k=1.5),
    "C  cap stop at 1.5 x ATR(D)":            dict(buf="fixed", cap_k=1.5),
    "D  lock +1R at +2R":                     dict(buf="fixed", lock=True),
    "E  time stop 30 days":                   dict(buf="fixed", max_days=30),
    "F  A + D":                               dict(buf="atr", lock=True),
}


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


def simulate(bars: pd.DataFrame, q: int, short: bool, entry: float, sl: float, tp: float,
             lock: bool, max_days: int | None) -> tuple[str, float, pd.Timestamp]:
    h, l, c, idx = bars["High"].to_numpy(), bars["Low"].to_numpy(), bars["Close"].to_numpy(), bars.index
    risk = abs(entry - sl)
    stop, stage = sl, 0                      # stage 1 = breakeven, 2 = +1R locked
    t_end = idx[q] + pd.Timedelta(days=max_days) if max_days else None
    for k in range(q, len(bars)):
        if t_end is not None and idx[k] >= t_end:
            return "time", c[k - 1], idx[k]
        if (h[k] >= stop) if short else (l[k] <= stop):
            return ("stop", "breakeven", "locked")[stage], stop, idx[k]
        if k > q and ((l[k] <= tp) if short else (h[k] >= tp)):
            return "target", tp, idx[k]
        if k > q:
            fav = (entry - l[k]) if short else (h[k] - entry)
            if stage == 0 and fav >= risk:
                stop, stage = entry, 1
            if lock and stage < 2 and fav >= 2 * risk:
                stop, stage = (entry - risk if short else entry + risk), 2
    return "open", c[-1], idx[-1]


def run_variant(trades: pd.DataFrame, bars: dict, a1: dict, aD: dict, v: dict) -> pd.DataFrame:
    rows = []
    for tr in trades.itertuples(index=False):
        sym, short = tr.symbol, tr.signal == "short"
        b = bars[sym]
        q = b.index.searchsorted(tr.entry_time)
        ext = tr.stop - SL_BUFFER[sym] if short else tr.stop + SL_BUFFER[sym]       # 4H sweep extreme
        t0 = tr.entry_time
        buf = 0.5 * a1[sym].asof(t0) if v["buf"] == "atr" else SL_BUFFER[sym]
        sl = ext + buf if short else ext - buf
        risk = abs(tr.entry - sl)
        d_atr = aD[sym].asof(t0)
        if v.get("skip_k") and risk > v["skip_k"] * d_atr:
            continue
        if v.get("cap_k") and risk > v["cap_k"] * d_atr:
            risk = v["cap_k"] * d_atr
            sl = tr.entry + risk if short else tr.entry - risk
        tp = tr.entry - 3 * risk if short else tr.entry + 3 * risk
        ex, px, t_exit = simulate(b, q, short, tr.entry, sl, tp, v.get("lock", False), v.get("max_days"))
        pnl = (tr.entry - px) if short else (px - tr.entry)
        rows.append({"symbol": sym, "signal": tr.signal, "entry_time": t0, "exit": ex, "risk": risk,
                     "r_net": (pnl - COST[sym]) / risk, "hold_days": (t_exit - t0).total_seconds() / 86400})
    return pd.DataFrame(rows)


def stats(g: pd.DataFrame) -> dict:
    win, loss = g.loc[g.r_net > 0, "r_net"].sum(), abs(g.loc[g.r_net < 0, "r_net"].sum())
    eq, peak, dd = 10_000.0, 10_000.0, 0.0
    for r in g.sort_values("entry_time").r_net:
        eq += eq * 0.01 * r
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak * 100)
    return {"trades": len(g), "win%": round(100 * (g.exit == "target").mean(), 1),
            "PF": round(win / loss, 2) if loss > 0 else float("inf"), "R": round(g.r_net.sum(), 2),
            "account": round(eq), "maxDD%": round(dd, 1), "avg_hold_d": round(g.hold_days.mean(), 1),
            "2025-26 R": round(g[g.entry_time >= "2025-01-01"].r_net.sum(), 2)}


def main() -> None:
    pd.set_option("display.width", 250)
    bars, a1, aD = {}, {}, {}
    for sym, (f1, _, f5) in SYMBOLS.items():
        h1 = load(DATA / f1)
        a1[sym] = atr(h1)
        d = build_htf(h1, "D")
        aD[sym] = atr(d).shift(1).set_axis(pd.DatetimeIndex(d["End"]))          # last COMPLETED day
        bars[sym] = {"5m": load(DATA / f5), "1h": h1}
    intr = pd.read_csv("output/backtest/trades.csv", parse_dates=["entry_time"])
    intr = intr[(intr.entry_tf == "5m") & (intr.entry_mode == "touch")].rename(columns={"entry_price": "entry"})
    sw = pd.read_csv("output/swing/trades.csv", parse_dates=["entry_time"])
    sw = sw[(sw.entry_type == "1H touch") & (sw.stop_type == "4H extreme") & (sw.target_type == "3R")]
    out = []
    for strat, trades, tf in (("intraday 5m touch", intr, "5m"), ("swing 1H touch", sw, "1h")):
        b = {s: bars[s][tf] for s in bars}
        for name, v in VARIANTS.items():
            res = run_variant(trades, b, a1, aD, v)
            for sym in ["US100", "XAUUSD"]:
                out.append({"strategy": strat, "variant": name, "symbol": sym, **stats(res[res.symbol == sym])})
    df = pd.DataFrame(out)
    df.to_csv("output/stop_experiments.csv", index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
