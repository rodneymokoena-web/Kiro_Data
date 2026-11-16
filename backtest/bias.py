"""Rule 1 bias (direction filter): SHORT bias / LONG bias from 4H swings and 4H FVGs, evaluated on closed 5m bars.

SHORT bias switches on when either
    SWEEP  a 5m bar trades above the latest confirmed 4H swing high (BIAS_PIVOT bars each side: a wick or a close both
           count as trading above) and a 5m bar closes back below it (the same bar or a later one);
    FVG    a closed 5m bar sits inside the latest 4H bearish FVG (close between its bottom and top).
LONG bias is the mirror image (sweep below the latest 4H swing low and a close back above it, or a close inside the
latest 4H bullish FVG).

DURATION  the bias lasts BIAS_BARS five-minute bars. Every new trigger (a sweep, or a close inside the FVG) restarts the
          count; an opposite trigger replaces the bias; if short and long trigger on the same bar nothing changes.
CAUSAL    the "latest" swing / FVG is the newest one already confirmed (swing: after its 5 right-hand bars; FVG: when its
          third 4H candle has closed) at the close of each 5m bar.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

import ifvg
import swings as S

BIAS_FILTER = os.environ.get('BIAS_FILTER', '0') == '1'   # default OFF
BIAS_PIVOT = int(os.environ.get('BIAS_PIVOT', 5))          # 4H swing size (bars each side)
BIAS_BARS = int(os.environ.get('BIAS_BARS', 500))         # bias duration in 5m bars
BIAS_SWEEP = os.environ.get('BIAS_SWEEP', '1') == '1'       # use the swing-sweep trigger
BIAS_FVG = os.environ.get('BIAS_FVG', '1') == '1'         # use the FVG trigger

_cache: dict = {}


def _ns(idx) -> np.ndarray:
    return pd.DatetimeIndex(idx).as_unit("ns").asi8


def compute_bias(h1: pd.DataFrame, m5: pd.DataFrame, pivot: int | None = None, bars: int | None = None,
                 sweep: bool | None = None, fvg: bool | None = None) -> np.ndarray:
    """Array aligned to m5.index: +1 long bias, -1 short bias, 0 none (value after each 5m bar closes)."""
    pivot = BIAS_PIVOT if pivot is None else pivot
    bars = BIAS_BARS if bars is None else bars
    sweep = BIAS_SWEEP if sweep is None else sweep
    fvg = BIAS_FVG if fvg is None else fvg
    key = (id(h1), id(m5), pivot, bars, sweep, fvg)
    if key in _cache:
        return _cache[key]

    h4 = S.build_htf(h1, "4H")
    saved = S.PIVOT_BY_TF
    S.PIVOT_BY_TF = {**saved, "4H": pivot}
    try:
        sw = S.find_swings(h4, "4H")
    finally:
        S.PIVOT_BY_TF = saved
    hi = sw[sw["type"] == "high"].sort_values("confirmed_time")
    lo = sw[sw["type"] == "low"].sort_values("confirmed_time")
    hi_t, hi_p = _ns(hi["confirmed_time"]), hi["price"].to_numpy(float)
    lo_t, lo_p = _ns(lo["confirmed_time"]), lo["price"].to_numpy(float)

    f = ifvg.find_fvgs(h4.drop(columns=["Start", "End"]))
    done = _ns(h4["End"])[f["idx"].to_numpy()] if len(f) else np.array([], "int64")
    bear = f["dir"].to_numpy() == "bear"
    bu_t, bu_b, bu_p = done[~bear], f["bottom"].to_numpy(float)[~bear], f["top"].to_numpy(float)[~bear]
    be_t, be_b, be_p = done[bear], f["bottom"].to_numpy(float)[bear], f["top"].to_numpy(float)[bear]

    close_ns = _ns(m5.index) + 5 * 60 * 10**9              # a 5m bar is known at its close
    H, L, C = (m5[k].to_numpy(float) for k in ("High", "Low", "Close"))
    ih = np.searchsorted(hi_t, close_ns, side="right") - 1  # latest confirmed 4H swing high / low per bar
    il = np.searchsorted(lo_t, close_ns, side="right") - 1
    ibe = np.searchsorted(be_t, close_ns, side="right") - 1  # latest 4H bearish / bullish FVG per bar
    ibu = np.searchsorted(bu_t, close_ns, side="right") - 1

    n = len(m5)
    out = np.zeros(n, dtype=np.int8)
    cur, cnt = 0, 0
    last_h, last_l = -2, -2
    pierced_h = pierced_l = False
    for t in range(n):
        short = long = False
        if sweep:
            if ih[t] != last_h:                              # a newer swing became "latest": forget the old pierce
                last_h, pierced_h = ih[t], False
            if il[t] != last_l:
                last_l, pierced_l = il[t], False
            if ih[t] >= 0:
                lvl = hi_p[ih[t]]
                if H[t] > lvl or C[t] > lvl:
                    pierced_h = True
                if pierced_h and C[t] < lvl:
                    short, pierced_h = True, False           # sweep consumed; a new one needs a new pierce
            if il[t] >= 0:
                lvl = lo_p[il[t]]
                if L[t] < lvl or C[t] < lvl:
                    pierced_l = True
                if pierced_l and C[t] > lvl:
                    long, pierced_l = True, False
        if fvg:
            if ibe[t] >= 0 and be_b[ibe[t]] <= C[t] <= be_p[ibe[t]]:
                short = True
            if ibu[t] >= 0 and bu_b[ibu[t]] <= C[t] <= bu_p[ibu[t]]:
                long = True
        if short != long:                                    # exactly one side triggered
            cur, cnt = (-1 if short else 1), bars
        elif cnt > 0:
            cnt -= 1
            if cnt == 0:
                cur = 0
        out[t] = cur
    _cache[key] = out
    return out


def allows(bias: np.ndarray, m5: pd.DataFrame, t, is_short: bool) -> bool:
    """Is the setup direction allowed by the bias that was active at time t (value after the last 5m bar closed by t)?"""
    i = int(np.searchsorted(_ns(m5.index), pd.Timestamp(t).as_unit("ns").value, side="left")) - 1
    if i < 0:
        return False
    return bias[i] == (-1 if is_short else 1)


def filter_setups(setups, h1, m5):
    """Keep only setups whose direction matches the bias active at their signal_time (no-op when BIAS_FILTER is off)."""
    if not BIAS_FILTER:
        return setups
    b = compute_bias(h1, m5)
    return [st for st in setups if allows(b, m5, st["signal_time"], st["signal"] == "short")]
