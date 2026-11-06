"""Intraday fast path: sweep -> 15m FVG inverted (15m IFVG) -> 15m CISD -> retest + 5m entry (rule 6).
SHORT described; LONG mirrored. One timeframe below the 1H-IFVG path (setups_v2), driven off 15m data.

    SWEEP       a Rule 1 level (session / 4H / D / W / M, ifvg.SWEEP_TFS + ifvg.SESSION_TFS) is taken, pinned to the
                15m candle in which it happens.
    15m FVG     a bullish 15m FVG formed by the sweep leg (candle 1 within LEG_15M candles before the sweep, middle
                candle at or before the 15m sweep candle), still intact at the sweep.
    INVERSION   within INVERT_15M 15m candles, the first 15m CLOSE below that FVG -> 15m IFVG, with 15m displacement
                (>= DISP_15M candles, >= 1 ATR).
    15m CISD    (REQUIRE_CISD) a 15m close through the CISD level: the open of the consecutive up-close 15m run that
                delivered price into the sweep extreme, confirmed by the inversion close.
    -> r5 signal on the 15m IFVG; entry_ltf.find_entry then retests it and enters on 5m (rule 6), stop prev 1H candle.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ifvg
import structure
import swings
from swings import TEST_START, add_break_times, build_htf, find_swings, session_levels

LEG_15M = 80          # 15m candles before the sweep that the 15m FVG may start within
INVERT_15M = 40       # 15m candles after the sweep for the inversion
DISP_15M = 2
REQUIRE_CISD = True
REQUIRE_MSS = True      # also need a 15m MSS (close through the last 15m swing before the extreme)
M15 = pd.Timedelta(minutes=15)


def _cisd_level(o, c, d, short):
    sgn = -1 if short else 1
    if d >= 0 and np.sign(c[d] - o[d]) == sgn:
        d -= 1
    m = d
    while m >= 0 and np.sign(c[m] - o[m]) == -sgn:
        m -= 1
    return o[m + 1] if d >= 0 and m < d else np.nan


def build_setups(h1: pd.DataFrame, m15: pd.DataFrame) -> list[dict]:
    """Returns setup dicts (each with an 'r5' 15m-IFVG signal) for the 5m entry stage."""
    htf = {tf: build_htf(h1, tf) for tf in ("D", "W", "M", "4H")}
    htf["1H"] = h1.assign(Start=h1.index, End=h1.index + pd.Timedelta(hours=1))
    parts = [find_swings(htf[tf], tf) for tf in ifvg.SWEEP_TFS if tf in htf]
    if ifvg.SESSION_TFS:
        parts.append(session_levels(h1, ifvg.SESSION_TFS))
    levels = pd.concat(parts, ignore_index=True)
    levels = add_break_times(levels, m15)
    levels = levels[levels["broken_time"].notna() & (levels["broken_time"] >= max(TEST_START, m15.index[0]))]

    o, h, l, c = (m15[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx, n = m15.index, len(m15)
    f15 = ifvg.find_fvgs(m15)
    atr = structure._arrays(m15)[4]
    saved = structure.DISP_MIN_CANDLES
    structure.DISP_MIN_CANDLES = DISP_15M
    out: dict[tuple, dict] = {}
    try:
        for lv in levels.sort_values("broken_time").itertuples(index=False):
            short = lv.type == "high"
            want = "bull" if short else "bear"
            s = idx.get_indexer([lv.broken_time])[0]
            if s < 0:
                continue
            cand = f15[(f15["dir"] == want) & (f15["idx"] - 2 >= s - LEG_15M) & (f15["idx"] - 1 <= s)]
            cand = cand.sort_values("idx", ascending=False)
            live = []
            for row in cand.itertuples(index=False):
                a = int(row.idx) + 1
                pre = c[a:s]
                if len(pre) and ((pre < row.bottom).any() if short else (pre > row.top).any()):
                    continue
                live.append((a, row))
            last_j = min(s + INVERT_15M, n - 1)
            f, j = None, -1
            for t in range(s, last_j + 1):
                act = [r for a, r in live if a <= t]
                if act and ((c[t] < act[0].bottom) if short else (c[t] > act[0].top)):
                    f, j = act[0], t
                    break
            if f is None:
                continue
            ok_d, run_len, move, _ = structure.displacement(m15, j, short)
            if not ok_d:
                continue
            ext = s + int(np.argmax(h[s:j + 1]) if short else np.argmin(l[s:j + 1]))
            if REQUIRE_CISD:
                lvl = _cisd_level(o, c, ext if np.sign(c[ext] - o[ext]) == (-1 if short else 1) else ext - 1, short)
                if np.isnan(lvl):
                    continue
                seg = c[ext:j + 1]
                if not ((seg < lvl).any() if short else (seg > lvl).any()):
                    continue
            if REQUIRE_MSS:
                ok_m, _lv, mi = structure.mss(m15, s, j, short, "ext")
                if not ok_m or mi > j:
                    continue
            key = (int(f.idx), want)
            tag = f"{lv.tf}{'H' if short else 'L'} {lv.price:.2f}"
            if key in out:
                if tag not in out[key]["swept_levels"]:
                    out[key]["swept_levels"] += f", {tag}"
                continue
            r5 = {"status": "signal", "retest_time": idx[s], "h1_fvg_time": idx[int(f.idx) - 2],
                  "h1_fvg_bottom": f.bottom, "h1_fvg_top": f.top, "h1_signal_time": idx[j] + M15,
                  "h1_signal_close": c[j], "h1_disp_candles": run_len, "h1_disp_atr": round(move / atr[j], 2),
                  "x": {"anchor": ext, "extreme": h[ext] if short else l[ext], "inval": n, "retest": s,
                        "origin": s, "fvg_idx": int(f.idx), "inv_idx": j, "n_candidates": len(live)}}
            out[key] = {
                "tf": "15m", "signal": "short" if short else "long", "swept_levels": tag, "sweep_time": lv.broken_time,
                "signal_time": idx[j] + M15, "extreme_time": idx[ext], "fvg_bottom": f.bottom, "fvg_top": f.top,
                "confirm": "15m IFVG" + ("+CISD" if REQUIRE_CISD else ""), "disp_candles": run_len,
                "disp_atr": round(move / atr[j], 2), "x_sweep_idx": s, "x_inv_idx": j, "x_fvg_idx": int(f.idx),
                "r5": r5, "fast15": True}
        return sorted(out.values(), key=lambda d: d["signal_time"])
    finally:
        structure.DISP_MIN_CANDLES = saved
