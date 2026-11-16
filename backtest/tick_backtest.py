"""Re-simulate the backtest trades (same signals, entry, stop, target) on Exness US Tech 100 ticks.

Usage:
    .venv/bin/python tick_backtest.py            (needs output/us100_runs/*.csv from make_us100_results.py and
                                                   data/exness_ticks/*.npz from fetch_exness_ticks.py)
Per trade (SHORT; LONG mirrored):
    OFFSET   Exness prices are shifted by the median (broker 1m close - Exness mid) over the 2 hours before entry.
    FILL     sell limit at the trade's entry: first tick from the entry candle on whose BID >= entry (up to
             FILL_CANDLES candles). Fill at the entry (at the bid if the first tick already gapped through it).
    EXIT     stop: first tick whose ASK >= stop, filled at that ask (gap slippage included). Target: first tick whose
             ASK <= target, filled at the target. Breakeven: once ASK <= entry - BE_AT_R x risk, stop -> entry.
    R        (fill - exit) / (stop - fill) for a short. Spread is in the bid/ask fills; no commission.
Writes output/tick_trades.csv and output/tick_summary.csv.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import make_us100_results as M
from swings import load

HERE = Path(__file__).parent
TICKS = HERE / "data" / "exness_ticks"
RUNS = HERE / "output" / "us100_runs"
BAR = {"swing": pd.Timedelta(hours=1), "intraday": pd.Timedelta(minutes=5)}
FILL_CANDLES = 3
TICK_SYMBOL = "USTEC"     # Exness tick files to use (USTEC | XAUUSD)
BE_AT_R = 1.0
_cache: dict[str, tuple] = {}


def _month(p: pd.Period):
    key = f"{p.year}_{p.month:02d}"
    if key not in _cache:
        if len(_cache) > 3:
            _cache.pop(next(iter(_cache)))
        f = TICKS / f"{TICK_SYMBOL}_{key}.npz"
        if not f.exists():
            _cache[key] = (np.array([], "int64"), np.array([]), np.array([]))
        else:
            z = np.load(f)
            t = z["t"]
            if len(t) and t[0] < 10**11:          # stored in seconds (pandas 3 unit) -> ms; tick order is kept
                t = t * 1000
            _cache[key] = (t, z["bid"], z["ask"])
    return _cache[key]


def _ms(ts: pd.Timestamp) -> int:
    return int(pd.Timestamp(ts).as_unit("ns").value // 1_000_000)


def ticks(t0: pd.Timestamp, t1: pd.Timestamp):
    parts = [_month(p) for p in pd.period_range(t0.tz_convert(None).to_period("M"), t1.tz_convert(None).to_period("M"), freq="M")]
    t = np.concatenate([p[0] for p in parts]); b = np.concatenate([p[1] for p in parts]); a = np.concatenate([p[2] for p in parts])
    lo, hi = np.searchsorted(t, _ms(t0)), np.searchsorted(t, _ms(t1))
    return t[lo:hi], b[lo:hi], a[lo:hi]


def offset(m1: pd.DataFrame, t0: pd.Timestamp) -> float:
    br = m1.loc[t0 - pd.Timedelta(hours=2):t0 - pd.Timedelta(minutes=1), "Close"]
    if br.empty:
        return np.nan
    t, b, a = ticks(br.index[0], t0)
    if not len(t):
        return np.nan
    ends = (br.index + pd.Timedelta(minutes=1)).as_unit("ns").asi8 // 1_000_000
    k = np.searchsorted(t, ends) - 1
    ok = k >= 0
    mid = (b[k[ok]] + a[k[ok]]) / 2
    return float(np.median(br.to_numpy()[ok] - mid)) if ok.any() else np.nan


def sim(tr: dict, model: str, m1: pd.DataFrame, data_end: pd.Timestamp, fixed_offset: float | None = None) -> dict:
    """fixed_offset: price shift for the ticks (0 when the trades come from the same Exness feed); None = measure."""
    short = tr["signal"] == "short"
    t0 = pd.Timestamp(tr["entry_time"])
    off = offset(m1, t0) if fixed_offset is None else fixed_offset
    if np.isnan(off):
        return {"tick_status": "no tick data"}
    entry, sl, tp = tr["entry"], tr["stop"], tr["target"]
    t, b, a = ticks(t0, t0 + FILL_CANDLES * BAR[model])
    b, a = b + off, a + off
    hit = np.flatnonzero(b >= entry) if short else np.flatnonzero(a <= entry)
    if not len(hit):
        return {"tick_status": "not filled", "offset": off}
    i = int(hit[0])
    fill = (max(entry, b[i]) if short else min(entry, a[i])) if i == 0 else entry
    t_fill = t[i]
    risk = abs(fill - sl)
    if (short and sl <= fill) or (not short and sl >= fill):
        return {"tick_status": "stop not beyond fill", "offset": off}
    span = pd.Timedelta(days=3)
    start = pd.Timestamp(t_fill, unit="ms", tz="UTC")
    stop, be = sl, False
    while True:
        end = min(start + span, data_end)
        t, b, a = ticks(start, end)
        b, a = b + off, a + off
        px = a if short else b                          # price at which the position is closed
        if len(t):
            mask = t >= t_fill
            t, px = t[mask], px[mask]
        if len(t):
            s_hit = np.flatnonzero(px >= stop) if short else np.flatnonzero(px <= stop)
            t_hit = np.flatnonzero(px <= tp) if short else np.flatnonzero(px >= tp)
            be_hit = np.array([], int)
            if not be and BE_AT_R is not None:
                lvl = fill - BE_AT_R * risk if short else fill + BE_AT_R * risk
                be_hit = np.flatnonzero(px <= lvl) if short else np.flatnonzero(px >= lvl)
            first = {k: int(v[0]) for k, v in (("stop", s_hit), ("target", t_hit), ("be", be_hit)) if len(v)}
            if first:
                kind = min(first, key=first.get)
                k = first[kind]
                if kind == "be" and ("stop" not in first or first["be"] < first["stop"]) and \
                        ("target" not in first or first["be"] < first["target"]):
                    stop, be = fill, True
                    t_fill = int(t[k]) + 1                 # continue after the breakeven tick
                    start = pd.Timestamp(t[k], unit="ms", tz="UTC")
                    continue
                if kind in ("stop", "be"):
                    kind = "stop"
                    k = first["stop"]
                exit_px = float(px[k]) if kind == "stop" else tp
                r = ((fill - exit_px) if short else (exit_px - fill)) / risk
                return {"tick_status": "ok", "offset": off, "tick_fill": fill,
                        "tick_exit": ("breakeven" if (kind == "stop" and be) else kind),
                        "tick_exit_price": exit_px, "tick_exit_time": pd.Timestamp(t[k], unit="ms", tz="UTC"),
                        "tick_r": r, "slip_pts": (exit_px - stop) * (1 if short else -1) if kind == "stop" else 0.0}
        if end >= data_end:
            last = float(px[-1]) if len(t) else fill
            r = ((fill - last) if short else (last - fill)) / risk
            return {"tick_status": "ok", "offset": off, "tick_fill": fill, "tick_exit": "open", "tick_exit_price": last,
                    "tick_exit_time": data_end, "tick_r": r, "slip_pts": 0.0}
        start, span = end, span * 2


def main() -> None:
    rows = []
    data_end = pd.Timestamp("2026-10-31", tz="UTC")
    for src in ("goat_oos", "goat", "pepperstone_oos", "pepperstone"):
        m1 = load(HERE / "data" / src / "US100_1m.csv")
        for model in ("swing", "intraday"):
            d = pd.read_csv(RUNS / f"{src}_{model}.csv", parse_dates=["entry_time", "exit_time"])
            for tr in d.sort_values("entry_time").to_dict("records"):
                res = sim(tr, model, m1, data_end)
                rows.append({"source": src, "broker": src.replace("_oos", ""), "model": model,
                             "entry_time": tr["entry_time"], "signal": tr["signal"], "entry": tr["entry"],
                             "stop": tr["stop"], "target": tr["target"], "candle_exit": tr["exit"],
                             "candle_r": tr["r_net"], **res})
            print("done", src, model, flush=True)
    t = pd.DataFrame(rows)
    t.to_csv(HERE / "output" / "tick_trades.csv", index=False)
    out = []
    for (b, m), g in t.groupby(["broker", "model"]):
        ok = g[g.tick_status == "ok"].sort_values("entry_time")
        sc, st = M.stats(ok["candle_r"]), M.stats(ok["tick_r"])
        out.append({"broker": b, "model": m, "trades": len(g), "simulated": len(ok),
                    "not filled on ticks": int((g.tick_status == "not filled").sum()),
                    "candle R": sc["R"], "tick R": st["R"], "candle PF": sc["PF"], "tick PF": st["PF"],
                    "candle win%": round(100 * sc["W"] / max(len(ok), 1)), "tick win%": round(100 * st["W"] / max(len(ok), 1)),
                    "candle capital": sc["account"], "tick capital": st["account"],
                    "candle DD%": sc["maxDD%"], "tick DD%": st["maxDD%"],
                    "outcome changed": int((ok["candle_exit"].replace({"breakeven": "be"}) !=
                                            ok["tick_exit"].replace({"breakeven": "be"})).sum()),
                    "avg stop slippage pts": round(ok.loc[ok.tick_exit == "stop", "slip_pts"].mean(), 2)})
    s = pd.DataFrame(out)
    s.to_csv(HERE / "output" / "tick_summary.csv", index=False)
    pd.set_option("display.width", 250)
    print(s.to_string(index=False))


if __name__ == "__main__":
    main()
