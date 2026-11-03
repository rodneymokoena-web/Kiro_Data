"""Revised intraday entry: 1H IFVG + 5m MSS, entry = limit at the 1H IFVG near edge, filled on 5m at the retest touch.
SHORT described; LONG is the mirror image. Rules 1-5 unchanged (backtest._intraday_setups -> 1H IFVG signal).

    MSS_MODE    "before": a 5m close below the last confirmed 5m swing low before the 5m sweep extreme, between the
                          extreme and the 1H IFVG signal close (the 5m MSS of the inversion move). Limit live from the
                          first 5m candle after the 1H signal.
                "after":  after the 1H signal, the first 5m close below the most recent confirmed 5m swing low (formed
                          before or after the signal); limit live from the next 5m candle.
                "none":   no MSS (reference).
    ENTRY       sell limit at the 1H IFVG bottom; fill = first 5m candle whose high reaches it (at the open if it opens
                above). Valid ENTRY_VALID after the 1H signal. Cancelled if price trades above the sweep extreme first.
    STOP        previous completed 1H candle high above the entry (backtest.prev_candle) + SL_BUFFER.
    TARGET      TARGET_R x risk; breakeven at +1R; same 5m candle stop + target -> stop (backtest.simulate).
"""
from __future__ import annotations

import contextlib
import io

import numpy as np
import pandas as pd

import backtest as B
import ifvg
from ifvg_1h import find_1h_ifvg, signal_key
from swings import DATA, SYMBOLS, load

MSS_MODE = "before"
MSS_PIVOT = 2
ENTRY_VALID = pd.Timedelta(hours=24)
TARGET_R = 3.0


def _piv_lows(l: np.ndarray, a: int, b: int, short: bool, h: np.ndarray, p: int = MSS_PIVOT) -> list[int]:
    out = []
    for i in range(max(a, p), min(b, len(l) - p - 1) + 1):
        if short and l[i] < l[i - p:i].min() and l[i] <= l[i + 1:i + 1 + p].min():
            out.append(i)
        if not short and h[i] > h[i - p:i].max() and h[i] >= h[i + 1:i + 1 + p].max():
            out.append(i)
    return out


def mss_5m(m5: pd.DataFrame, arr, st: dict, r5: dict, short: bool) -> int:
    """5m index at whose close the MSS confirms; -1 = none. arr = (o, h, l, c) arrays of m5."""
    o, h, l, c = arr
    idx = m5.index
    sig = idx.searchsorted(r5["h1_signal_time"])                  # first 5m candle after the 1H signal
    if MSS_MODE == "before":
        ext_t = r5["x"]
        a1 = idx.searchsorted(st["extreme_time"])
        a2 = idx.searchsorted(st["extreme_time"] + st.get("extreme_span", pd.Timedelta(hours=4)))
        if a2 <= a1:
            return -1
        ext = a1 + int(np.argmax(h[a1:a2]) if short else np.argmin(l[a1:a2]))
        piv = [i for i in _piv_lows(l, ext - 300, ext - 1, short, h)]
        if not piv:
            return -1
        p = piv[-1]
        lv = l[p] if short else h[p]
        for t in range(max(ext, p + MSS_PIVOT + 1), sig):
            if (short and c[t] < lv) or (not short and c[t] > lv):
                return t
        return -1
    if MSS_MODE == "after":
        end = min(idx.searchsorted(r5["h1_signal_time"] + ENTRY_VALID), len(c))
        piv = _piv_lows(l, sig - 300, end, short, h)
        piv = np.asarray(piv, int)
        for t in range(sig, end):
            ok = piv[piv + MSS_PIVOT < t]
            if not len(ok):
                continue
            lv = l[ok[-1]] if short else h[ok[-1]]
            if (short and c[t] < lv) or (not short and c[t] > lv):
                return t
        return -1
    return sig - 1                                                # "none": live straight after the signal


def run(mss_mode: str | None = None) -> pd.DataFrame:
    global MSS_MODE
    if mss_mode is not None:
        MSS_MODE = mss_mode
    trades = []
    for symbol, (h1_file, _, m5_file) in SYMBOLS.items():
        h1 = load(DATA / h1_file)
        m5 = load(DATA / m5_file)
        arr = tuple(m5[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
        o, h, l, c = arr
        with contextlib.redirect_stdout(io.StringIO()):
            h4, setups = B._intraday_setups(h1)
        h1_fvgs = ifvg.find_fvgs(h1)
        seen = set()
        for n, st in enumerate(setups, 1):
            r5 = find_1h_ifvg(st, h1, h1_fvgs)
            if r5["status"] != "signal" or signal_key(st, r5) in seen:
                continue
            seen.add(signal_key(st, r5))
            short = st["signal"] == "short"
            m = mss_5m(m5, arr, st, r5, short)
            if m < 0:
                continue
            level = r5["h1_fvg_bottom"] if short else r5["h1_fvg_top"]
            extreme = r5["x"]["extreme"]
            q0 = max(m5.index.searchsorted(r5["h1_signal_time"]), m + 1)
            q1 = min(m5.index.searchsorted(r5["h1_signal_time"] + ENTRY_VALID), len(m5))
            q, entry = -1, np.nan
            for i in range(q0, q1):
                if (short and h[i] > extreme) or (not short and l[i] < extreme):
                    break                                          # beyond the sweep extreme -> cancelled
                if (short and h[i] >= level) or (not short and l[i] <= level):
                    q, entry = i, (max(level, o[i]) if short else min(level, o[i]))
                    break
            if q < 0:
                continue
            pc = B.prev_candle(h1, m5.index[q], pd.Timedelta(hours=1), short, entry, B.PREV_CANDLE_LOOKBACK)
            if np.isnan(pc):
                continue
            sl = pc + B.SL_BUFFER[symbol] if short else pc - B.SL_BUFFER[symbol]
            if (short and sl <= entry) or (not short and sl >= entry):
                continue
            risk = abs(entry - sl)
            tp = entry - TARGET_R * risk if short else entry + TARGET_R * risk
            sim = B.simulate(m5, q, short, entry, sl, tp)
            pnl = (entry - sim["exit_price"]) if short else (sim["exit_price"] - entry)
            trades.append({"symbol": symbol, "setup": n, "signal": st["signal"], "1h_signal_time": r5["h1_signal_time"],
                           "mss_time": m5.index[m], "entry_time": m5.index[q], "entry": entry, "stop": sl, "target": tp,
                           "risk_pts": risk, "exit": sim["exit"], "exit_time": m5.index[sim["exit_idx"]],
                           "exit_price": sim["exit_price"], "pnl_pts": pnl, "r_net": (pnl - B.COST[symbol]) / risk})
    return pd.DataFrame(trades)


if __name__ == "__main__":
    t = run()
    pd.set_option("display.width", 220)
    print(t.tail(20).to_string(index=False) if len(t) else "no trades")
