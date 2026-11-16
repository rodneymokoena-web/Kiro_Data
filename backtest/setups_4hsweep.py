"""Rule 1b: 4H swing sweeps use a 1H FVG -> 1H IFVG (one timeframe below the swept level). SHORT described.

Swing model (swing_setups): the snapshot rules one timeframe down.
    SWEEP       a 1H wick trades above a 4H swing high (PIVOT_4H candles each side, confirmed after PIVOT_4H candles).
    1H FVG      the LAST bullish 1H FVG of the leg that swept it (middle candle at or before the 1H sweep candle, candle 1
                within LEG_1H 1H candles before the sweep), no 1H close below it before the sweep. Causal: at each 1H
                candle the active FVG is the last intact one already complete.
    INVERSION   within INVERT_WINDOW_1H 1H candles of the sweep, the first 1H CLOSE below that FVG, with 1H displacement
                (>= DISP_MIN_1H candles, >= 1 ATR) and a 1H MSS (close below the last 1H swing low before the extreme).
    -> setup with fvg_bottom/top = the 1H IFVG, fvg_tf = "1H"; swing_snap.py then trades it like a 4H IFVG (limit at
       the near edge, stop above the 1H OB 50% of the drop, target the 1H swing low before the FVG's middle candle).
Intraday model: setups_v2.build_setups with SWEEP_TFS = ("4H",) (1H FVG of the leg inverted with displacement + MSS
    -> 1H IFVG signal straight away; then rule 6 entry as usual) - see backtest._intraday_setups.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ifvg
import structure
import swings
from swings import TEST_START, add_break_times, build_htf, find_swings

PIVOT_4H = 5
LEG_1H = 60
INVERT_WINDOW_1H = 20
DISP_MIN_1H = 1
H1 = pd.Timedelta(hours=1)


def frame(h1: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Candles with Start/End for find_swings: 1H = the 1H bars themselves, else swings.build_htf."""
    if tf == "1H":
        return h1.assign(Start=h1.index, End=h1.index + H1)
    return build_htf(h1, tf)


POI_TF = {"4H": "D", "1H": "4H"}      # point of interest for each swept level timeframe
USE_POI = False


def poi_filter(levels: pd.DataFrame, h1: pd.DataFrame, poi_tf: str) -> pd.DataFrame:
    """Keep sweeps that trade into an active OPPOSING FVG of poi_tf (SHORT: a bearish FVG). Active = complete before
    the sweep and not closed through (bearish: no poi_tf close above its top) before the sweep candle. Into = the range
    swept level -> sweep candle high overlaps the FVG zone."""
    if levels.empty:
        return levels
    bars = frame(h1, poi_tf)
    f = ifvg.find_fvgs(bars.drop(columns=["Start", "End"]))
    end = pd.DatetimeIndex(bars["End"])
    start = pd.DatetimeIndex(bars["Start"])
    inv = f["inv_idx"].to_numpy()
    far = pd.Timestamp("2262-01-01", tz="UTC")
    f = f.assign(done=end[f["idx"].to_numpy()],
                 inv_start=[start[k] if k >= 0 else far for k in inv])
    hi, lo = h1["High"], h1["Low"]
    keep = []
    for lv in levels.itertuples(index=False):
        t = lv.broken_time
        short = lv.type == "high"
        x = hi.at[t] if short else lo.at[t]
        a, b = (lv.price, x) if short else (x, lv.price)
        g = f[(f["dir"] == ("bear" if short else "bull")) & (f["done"] <= t) &
              (f["inv_start"] > t) & (f["bottom"] <= b) & (f["top"] >= a)]
        keep.append(not g.empty)
    return levels[np.array(keep, bool)]


def levels_4h(h1: pd.DataFrame, pivot: int, tf: str = "4H") -> pd.DataFrame:
    saved = dict(swings.PIVOT_BY_TF)
    swings.PIVOT_BY_TF = {**saved, tf: pivot}
    try:
        lv = find_swings(frame(h1, tf), tf)
    finally:
        swings.PIVOT_BY_TF = saved
    lv = add_break_times(lv, h1)
    lv = lv[lv["broken_time"].notna() & (lv["broken_time"] >= max(TEST_START, h1.index[0]))]
    return poi_filter(lv, h1, POI_TF[tf]) if USE_POI else lv


def swing_setups(h1: pd.DataFrame, pivot: int = PIVOT_4H, tf: str = "4H") -> list[dict]:
    """tf = timeframe of the swept swing levels ("4H" rule 1b, "1H" rule 1c); the FVG / IFVG is always 1H."""
    o, h, l, c = (h1[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx1, n1 = h1.index, len(h1)
    f1 = ifvg.find_fvgs(h1)
    saved = structure.DISP_MIN_CANDLES
    structure.DISP_MIN_CANDLES = DISP_MIN_1H
    out: dict[tuple, dict] = {}
    try:
        for lv in levels_4h(h1, pivot, tf).sort_values("broken_time").itertuples(index=False):
            short = lv.type == "high"
            want = "bull" if short else "bear"
            s1 = idx1.get_indexer([lv.broken_time])[0]
            if s1 < 0:
                continue
            cand = f1[(f1["dir"] == want) & (f1["idx"] - 2 >= s1 - LEG_1H) & (f1["idx"] - 1 <= s1)]
            cand = cand.sort_values("idx", ascending=False)
            live = []
            for row in cand.itertuples(index=False):
                a = int(row.idx) + 1                       # first 1H candle after the FVG is complete
                pre = c[a:s1]
                if len(pre) and ((pre < row.bottom).any() if short else (pre > row.top).any()):
                    continue
                live.append((a, row))
            last_j = min(s1 + INVERT_WINDOW_1H, n1 - 1)
            f, j = None, -1
            for t in range(s1, last_j + 1):
                act = [r for a, r in live if a <= t]
                if not act:
                    continue
                r = act[0]
                if (c[t] < r.bottom) if short else (c[t] > r.top):
                    f, j = r, t
                    break
            if f is None:
                continue
            ok_d, run_len, move, _ = structure.displacement(h1, j, short)
            if not ok_d:
                continue
            ok_m, mss_lv, mss_i = structure.mss(h1, s1, j, short, "ext")
            if not ok_m or mss_i > j:
                continue
            key = (int(f.idx), want)
            tag = f"{tf}{'H' if short else 'L'} {lv.price:.2f}"
            if key in out:
                if tag not in out[key]["swept_levels"]:
                    out[key]["swept_levels"] += f", {tag}"
                continue
            ext1 = s1 + int(np.argmax(h[s1:j + 1]) if short else np.argmin(l[s1:j + 1]))
            atr_j = structure._arrays(h1)[4][j]
            out[key] = {
                "tf": "1H", "fvg_tf": "1H", "signal": "short" if short else "long", "swept_levels": tag,
                "sweep_time": lv.broken_time, "fvg_time": idx1[int(f.idx) - 2], "fvg_bottom": f.bottom, "fvg_top": f.top,
                "inversion_time": idx1[j], "inversion_close": c[j], "signal_time": idx1[j] + H1,
                "extreme_time": idx1[ext1], "extreme_span": H1, "confirm": "MSS1H", "mss_level": mss_lv,
                "disp_candles": run_len, "disp_atr": round(move / atr_j, 2),
                "x_sweep_idx": s1, "x_inv_idx": j, "x_fvg_idx": int(f.idx),
            }
    finally:
        structure.DISP_MIN_CANDLES = saved
    return sorted(out.values(), key=lambda d: d["signal_time"])
