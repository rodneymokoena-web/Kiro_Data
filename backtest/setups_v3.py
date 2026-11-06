"""Revised rule 3 (v3): the 4H FVG of rule 2 is inverted by a 1H CLOSE; displacement and MSS on 1H, CISD on 4H.

SHORT described (D/W/M high swept); LONG is the mirror image.
    1. SWEEP     a 1H wick trades above a D/W/M swing high (rule 1, ifvg.SWEEP_TFS). s1 = 1H sweep candle,
                 s4 = the 4H candle containing it.
    2. 4H FVG    rule 2 unchanged: the LAST bullish 4H FVG of the sweeping leg (middle candle at or before s4,
                 candle 1 within ifvg.leg_origin), still intact at the sweep (no 1H close below it before s1).
    3. INVERSION INVERT_ON "close": the first 1H candle that CLOSES below that 4H FVG, within INVERT_WINDOW_1H
                 1H candles of s1. INVERT_ON "wick": the first 1H candle after the sweep whose LOW trades below
                 the FVG; WICK_CLOSE keeps it only if it closes below it ("through"), inside it ("inside"),
                 back above it ("back") or anywhere ("any").
       DISPLACEMENT  on 1H: that 1H candle ends a run of >= 2 bearish 1H candles moving >= 1 x ATR(14) on 1H.
       MSS       on 1H: close below the last confirmed 1H swing low before the 1H sweep extreme.
       CISD      on 4H: level = open of the first of the consecutive bullish 4H candles that delivered price
                 into the 4H candle of the extreme. Confirmation depends on CISD_MODE:
                   "4h_close"  a completed 4H candle closed below the level by the 1H inversion close (strict)
                   "1h_close"  any 1H close below the 4H CISD level, from the extreme to the inversion candle
       REQUIRE   "or" = displacement AND (4H CISD or 1H MSS);  "and" = displacement AND 4H CISD AND 1H MSS
                 "mss" = displacement AND 1H MSS only (no 4H CISD at all)
       MSS_MODE  "ext" = 1H swing low before the sweep extreme (structure.quality); "any" = the most recent confirmed
                 1H swing low, formed before or after the sweep (structure.mss)
       WAIT_1H   0 = everything confirmed by the inversion candle close. > 0 = CISD/MSS may confirm up to WAIT_1H
                 1H candles later while the 4H FVG stays inverted (no 1H close back above its top) and price
                 stays below the extreme; the signal is then at the confirming close.
    -> 4H IFVG setup with signal_time = close of the confirming 1H candle. Rules 4-7 unchanged (4H IFVG retest
       -> 1H IFVG -> entry). extreme_time = 1H extreme candle (extreme_span 1H, no look-ahead).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ifvg
import structure
from swings import TEST_START, add_break_times, build_htf, find_swings

INVERT_WINDOW_1H = 80        # 1H candles after the sweep (= 20 x 4H, same as the 4H rule)
CISD_MODE = "4h_close"       # "4h_close" | "1h_close"
REQUIRE = "or"               # "or" | "and" | "mss"
MSS_MODE = "ext"             # "ext" | "any"
WAIT_1H = 0                  # 0 = strict; > 0 = CISD/MSS may confirm this many 1H candles after the inversion
INVERT_ON = "close"          # "close" = first 1H CLOSE through the 4H FVG
                             # "wick"  = first 1H candle after the sweep whose LOW trades below the FVG bottom
                             #           (HIGH above the top, for a long), filtered by where it closes (WICK_CLOSE)
WICK_CLOSE = "any"           # "through" = closes below the FVG (a) | "inside" = closes inside it (b)
                             # "back" = closes back above it (c) | "any" = any close
H1 = pd.Timedelta(hours=1)
STATS: dict[str, int] = {}     # funnel counters (reset by the caller): stage -> number of sweeps reaching it


def _c(name: str) -> None:
    STATS[name] = STATS.get(name, 0) + 1


def _cisd_level_4h(o4, c4, d: int, short: bool) -> float:
    """Open of the first candle of the consecutive delivery run (bullish for a short) ending at 4H candle d."""
    sgn = -1 if short else 1
    if d >= 0 and np.sign(c4[d] - o4[d]) == sgn:        # extreme candle itself closed as a reversal candle
        d -= 1
    m = d
    while m >= 0 and np.sign(c4[m] - o4[m]) == -sgn:
        m -= 1
    return o4[m + 1] if d >= 0 and m < d else np.nan


def build_setups(h1: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    htf = {tf: build_htf(h1, tf) for tf in ("D", "W", "M", "4H")}
    h4_full = htf["4H"]
    h4 = h4_full.drop(columns=["Start", "End"])
    end4 = h4_full["End"]
    end_idx = pd.DatetimeIndex(end4)
    import swings as _S
    parts = [find_swings(htf[tf], tf) if not (tf == "4H" and ifvg.SIG_4H) else _S.significant_4h_levels(h1)
             for tf in ifvg.SWEEP_TFS]       # rule 1 liquidity
    if ifvg.SESSION_TFS:
        parts.append(_S.session_levels(h1, ifvg.SESSION_TFS))
    if ifvg.FVG_LIQ:
        parts.append(_S.fvg_far_edge_levels(h4_full))
    levels = pd.concat(parts, ignore_index=True)
    levels = levels[levels["tf"].isin(tuple(ifvg.SWEEP_TFS) + tuple(ifvg.SESSION_TFS) + (("4HFVG",) if ifvg.FVG_LIQ else ()))]
    import swings as _S
    sweep_bars = h1 if _S.SWEEP_TF in ("1H", None) else _S._sweep_frame(h1, _S.SWEEP_TF)
    levels = add_break_times(levels, sweep_bars)
    if sweep_bars is not h1:                              # snap the sweep time onto the 1H candle that contains it
        snapped = []
        for t in levels["broken_time"]:
            if pd.isna(t):
                snapped.append(pd.NaT)
            else:
                p = int(h1.index.searchsorted(t, side="right")) - 1
                snapped.append(h1.index[p] if p >= 0 else pd.NaT)
        levels = levels.assign(broken_time=snapped)
    levels = levels[levels["broken_time"].notna() & (levels["broken_time"] >= max(TEST_START, h1.index[0]))]

    o4, hh4, ll4, c4 = (h4[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    h, l, c = h1["High"].to_numpy(), h1["Low"].to_numpy(), h1["Close"].to_numpy()
    idx1, idx4, n1 = h1.index, h4.index, len(h1)
    f4 = ifvg.find_fvgs(h4)
    out: dict[tuple, dict] = {}
    for lv in levels.sort_values("broken_time").itertuples(index=False):
        short = lv.type == "high"
        want = "bull" if short else "bear"
        s1 = idx1.get_indexer([lv.broken_time])[0]
        s4 = idx4.searchsorted(lv.broken_time, side="right") - 1
        if s1 < 0 or s4 < 0:
            continue
        _c("1 level swept")
        # ---- rule 2: last 4H FVG of the sweeping leg, intact (1H closes) at the sweep
        origin4 = ifvg.leg_origin(o4, hh4, ll4, c4, s4, short)
        if origin4 < 0:
            continue
        cand = f4[(f4["dir"] == want) & (f4["idx"] - 2 >= origin4) & (f4["idx"] - 1 <= s4)]
        cand = cand.sort_values("idx", ascending=False)
        last_j = min(s1 + INVERT_WINDOW_1H, n1 - 1)
        # intact candidates (no 1H close through them before the sweep), with the first 1H candle at which each is
        # known (a = first 1H candle after its 4H candle 3 closed)
        live = []
        for row in cand.itertuples(index=False):
            a = idx1.searchsorted(end4.iat[int(row.idx)])
            pre = c[a:s1]
            if len(pre) and ((pre < row.bottom).any() if short else (pre > row.top).any()):
                continue
            live.append((a, row))
        # causal: at each 1H candle t the rule 2 FVG is the LAST intact candidate already complete at t (a newer one
        # completing after the sweep replaces an older one that has not been hit yet). The first hit is final.
        f, j = None, -1
        for t in range(s1, last_j + 1):
            act = [r for a, r in live if a <= t]
            if not act:
                continue
            r = act[0]                # cand is sorted newest first
            hit = ((c[t] < r.bottom if short else c[t] > r.top) if INVERT_ON == "close"
                   else (l[t] < r.bottom if short else h[t] > r.top))
            if hit:
                f, j = r, t
                break
        _c("2 intact 4H FVG exists") if live else None
        if f is None:
            continue
        _c("3 inverted by a 1H close in the window")
        if INVERT_ON == "wick" and WICK_CLOSE != "any":
            through = c[j] < f.bottom if short else c[j] > f.top
            back = c[j] > f.top if short else c[j] < f.bottom
            kind = "through" if through else "back" if back else "inside"
            if kind != WICK_CLOSE:
                continue
        # ---- rule 3: displacement on 1H at the inversion candle
        ok_d, run_len, move, _ = structure.displacement(h1, j, short)
        if not ok_d:
            continue
        _c("4 1H displacement ok")
        ext1 = s1 + int(np.argmax(h[s1:j + 1]) if short else np.argmin(l[s1:j + 1]))
        extreme = h[ext1] if short else l[ext1]
        # confirmation window: inversion candle (+ WAIT_1H while still inverted and extreme intact)
        w_end = min(j + WAIT_1H, n1 - 1)
        if WAIT_1H:
            for t in range(j + 1, w_end + 1):
                broken = (h[t] > extreme or c[t] > f.top) if short else (l[t] < extreme or c[t] < f.bottom)
                if broken:
                    w_end = t - 1
                    break
        # MSS on 1H (first close through the last 1H swing before the extreme, from the extreme up to w_end)
        ok_m, mss_lv, mss_i = structure.mss(h1, s1, w_end, short, MSS_MODE)
        # CISD on 4H
        e4 = idx4.searchsorted(idx1[ext1], side="right") - 1                  # 4H candle of the extreme
        k4_w = int(end_idx.searchsorted(idx1[w_end] + H1, side="right")) - 1
        level = _cisd_level_4h(o4, c4, min(e4, max(k4_w, e4 - 1)), short) if e4 >= 0 else np.nan
        cisd_i = -1                                               # 1H index at whose close the CISD is confirmed
        if pd.notna(level):
            if CISD_MODE == "4h_close":
                for t4 in range(e4, k4_w + 1):
                    if (short and c4[t4] < level) or (not short and c4[t4] > level):
                        cisd_i = idx1.searchsorted(end4.iat[t4]) - 1
                        break
            else:
                seg = c[ext1:w_end + 1]
                hit = np.where(seg < level if short else seg > level)[0]
                cisd_i = ext1 + int(hit[0]) if len(hit) else -1
        conf = [x for x in (cisd_i, mss_i) if x >= 0]
        if REQUIRE == "none":                  # no MSS / CISD requirement (displacement only)
            cisd_i = mss_i = -1
            sig = j
        elif REQUIRE == "mss":
            if mss_i < 0:
                continue
            cisd_i = -1
            sig = max(j, mss_i)
        elif REQUIRE == "and":
            if cisd_i < 0 or mss_i < 0:
                continue
            sig = max(j, cisd_i, mss_i)
        else:
            if not conf:
                continue
            sig = max(j, min(conf))
        if sig > w_end:
            continue
        _c("5 1H MSS ok")
        key = (int(f.idx), want)
        tag = f"{lv.tf}{'H' if short else 'L'} {lv.price:.2f}"
        if key in out:
            if tag not in out[key]["swept_levels"]:
                out[key]["swept_levels"] += f", {tag}"
            continue
        atr_j = structure._arrays(h1)[4][j]
        confirm = "+".join(n for n, x in (("CISD4H", cisd_i), ("MSS1H", mss_i)) if 0 <= x <= sig) or "-"
        out[key] = {
            "tf": "4H", "signal": "short" if short else "long", "swept_levels": tag, "sweep_time": lv.broken_time,
            "fvg_time": idx4[int(f.idx) - 2], "fvg_bottom": f.bottom, "fvg_top": f.top,
            "inversion_time": idx1[j], "inversion_close": c[j],
            "signal_time": idx1[sig] + H1, "extreme_time": idx1[ext1], "extreme_span": H1,
            "confirm": confirm, "cisd_level": level, "mss_level": mss_lv,
            "disp_candles": run_len, "disp_atr": round(move / atr_j, 2),
            "x_sweep_idx": s4, "x_inv_idx": int(idx4.searchsorted(idx1[j], side="right") - 1), "x_fvg_idx": int(f.idx), "x_inv_idx_1h": j, "x_sweep_idx_1h": s1,
        }
    setups = sorted(out.values(), key=lambda d: d["signal_time"])
    return h4, setups
