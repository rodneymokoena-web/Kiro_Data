"""Rule 4: 4H inversion quality - displacement (>= 2 candles) AND (CISD or MSS).

Used as the `accept` filter for ifvg.find_setups on the 4H chart.

For a SHORT (high swept, bullish FVG inverted). LONG is the mirror image.
    extreme      = highest high from the sweep candle to the inversion candle
    DISPLACEMENT = the inversion candle is the last of a run of >= DISP_MIN_CANDLES consecutive
                   bearish candles (close < open), each with body >= DISP_BODY_RATIO of its range
                   (default 0 = no body requirement), and the run moves >= DISP_MIN_ATR x ATR(14)
                   (first open -> last close).
    CISD         = the consecutive bullish candles that delivered price into the extreme;
                   CISD level = OPEN of the first of them. Confirmed when a candle closes below it.
    MSS          = last confirmed 4H swing low (MSS_PIVOT bars each side) before the extreme.
                   Confirmed when a candle closes below it.
    PASS         = displacement AND (CISD or MSS), both confirmed by the inversion candle's close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DISP_MIN_CANDLES = 2
DISP_BODY_RATIO = 0.0   # 0 = any candle closing in the move direction; 0.3-0.5 = demand strong bodies
DISP_MIN_ATR = 1.0
MSS_PIVOT = 2


def _atr(bars: pd.DataFrame, n: int = 14) -> np.ndarray:
    pc = bars["Close"].shift(1)
    tr = pd.concat([bars["High"] - bars["Low"], (bars["High"] - pc).abs(), (bars["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean().to_numpy()


_cache: dict[int, tuple] = {}   # id(bars) -> (bars, arrays); several frames (1H + 4H) may be in use at once


def _arrays(bars: pd.DataFrame):
    key = id(bars)
    hit = _cache.get(key)
    if hit is None or hit[0] is not bars:
        if len(_cache) >= 4:
            _cache.clear()
        o, h, l, c = (bars[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
        hit = _cache[key] = (bars, (o, h, l, c, _atr(bars)))
    return hit[1]


def _swing_points(h: np.ndarray, l: np.ndarray, upto: int, kind: str) -> list[int]:
    """Indices of confirmed pivots (MSS_PIVOT each side) whose confirmation bar <= upto."""
    p = MSS_PIVOT
    out = []
    for i in range(p, min(upto - p, len(h) - p - 1) + 1):
        if kind == "low" and l[i] < l[i - p:i].min() and l[i] <= l[i + 1:i + 1 + p].min():
            out.append(i)
        if kind == "high" and h[i] > h[i - p:i].max() and h[i] >= h[i + 1:i + 1 + p].max():
            out.append(i)
    return out


def displacement(bars: pd.DataFrame, j: int, short: bool) -> tuple[bool, int, float, int]:
    """Run of consecutive candles closing in the trade direction that ends at candle j.
    Returns (passed, n_candles, move_in_price, run_start_index)."""
    o, h, l, c, atr = _arrays(bars)
    sgn = -1 if short else 1
    k = j
    while k >= 0 and np.sign(c[k] - o[k]) == sgn and abs(c[k] - o[k]) >= DISP_BODY_RATIO * (h[k] - l[k]):
        k -= 1
    run_start, run_len = k + 1, j - k
    run_move = abs(c[j] - o[run_start]) if run_len else 0.0
    return run_len >= DISP_MIN_CANDLES and run_move >= DISP_MIN_ATR * atr[j], run_len, run_move, run_start


def mss(bars: pd.DataFrame, s: int, j: int, short: bool, mode: str = "ext") -> tuple[bool, float, int]:
    """MSS on `bars` between the sweep candle s and candle j (inclusive). SHORT: a close below a previous swing low.
    mode "ext": the last confirmed swing low before the sweep extreme (extreme = highest high s..j), broken by a close
                from the extreme on (same definition as quality()).
    mode "any": at each candle t from the sweep on, the most recent swing low already confirmed (pivot + MSS_PIVOT < t),
                formed before OR after the sweep / extreme; MSS = first close below it.
    Returns (ok, level, index of the breaking candle or -1)."""
    o, h, l, c, _ = _arrays(bars)
    if mode == "ext":
        q = quality(bars, {"inv_idx": j}, s, "bull" if short else "bear")
        if pd.isna(q["mss_time"]):
            return False, q["mss_level"], -1
        return True, q["mss_level"], int(bars.index.get_indexer([q["mss_time"]])[0])
    p = MSS_PIVOT
    piv = _swing_points(h, l, j, "low" if short else "high")     # confirmed by candle i + p <= j
    piv = np.asarray(piv, dtype=int)
    for t in range(s, j + 1):
        ok_p = piv[piv + p < t]
        if not len(ok_p):
            continue
        i = int(ok_p[-1])
        lv = l[i] if short else h[i]
        if (short and c[t] < lv) or (not short and c[t] > lv):
            return True, lv, t
    return False, np.nan, -1


def quality(bars: pd.DataFrame, fvg, sweep_idx: int, fvg_dir: str) -> dict:
    o, h, l, c, atr = _arrays(bars)
    j = int(fvg["inv_idx"])
    short = fvg_dir == "bull"            # bullish FVG inverted -> short
    sgn = -1 if short else 1             # direction of the reversal move
    ext = sweep_idx + int(np.argmax(h[sweep_idx:j + 1]) if short else np.argmin(l[sweep_idx:j + 1]))

    # ---- displacement: run of consecutive candles in the reversal direction ending at j
    disp, run_len, run_move, run_start = displacement(bars, j, short)

    # ---- CISD: open of the first candle of the delivery run into the extreme
    d = ext if np.sign(c[ext] - o[ext]) == -sgn else ext - 1   # extreme candle may itself be a reversal candle
    m = d
    while m >= 0 and np.sign(c[m] - o[m]) == -sgn:
        m -= 1
    cisd_level, cisd_time = np.nan, pd.NaT
    if d >= 0 and m < d:
        cisd_level = o[m + 1]
        for t in range(ext, j + 1):
            if (short and c[t] < cisd_level) or (not short and c[t] > cisd_level):
                cisd_time = bars.index[t]
                break

    # ---- MSS: last confirmed opposite swing before the extreme
    pivots = _swing_points(h, l, j, "low" if short else "high")
    pivots = [p for p in pivots if p < ext]
    mss_level, mss_time = np.nan, pd.NaT
    if pivots:
        p = pivots[-1]
        mss_level = l[p] if short else h[p]
        for t in range(max(ext, p + MSS_PIVOT + 1), j + 1):
            if (short and c[t] < mss_level) or (not short and c[t] > mss_level):
                mss_time = bars.index[t]
                break

    cisd, mss = pd.notna(cisd_time), pd.notna(mss_time)
    reasons = []
    if not disp:
        reasons.append(f"displacement {run_len} candle(s), {run_move / atr[j]:.2f} ATR")
    if not (cisd or mss):
        reasons.append("no CISD/MSS")
    return {
        "passed": bool(disp and (cisd or mss)),
        "reject_reason": "; ".join(reasons),
        "disp_candles": int(run_len), "disp_atr": round(float(run_move / atr[j]), 2),
        "disp_start_time": bars.index[run_start] if run_len else pd.NaT,
        "cisd_level": cisd_level, "cisd_time": cisd_time,
        "mss_level": mss_level, "mss_time": mss_time,
        "confirm": "+".join(n for n, ok in (("CISD", cisd), ("MSS", mss)) if ok) or "-",
        "x_ext_idx": ext,
    }
