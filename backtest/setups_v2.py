"""Revised rules 1-3: D relative equal highs/lows swept -> 4H FVG in the leg -> 1H FVG of the leg inverted by a 1H
close with displacement + MSS. Produces the 1H IFVG signal used by the entries (rule 6 intraday / swing 1H).

SHORT described (relative equal HIGHS swept = buy-side stops); LONG is the mirror image.
    1. SWEEP   a wick trades above a D relative equal high (swings.find_swings, rule 1; ifvg.SWEEP_TFS).
               The sweep moment is pinned to the 1H candle in which it happens.
    2. LEG     starts at ifvg.leg_origin on 4H (LEG_MODE "swing" = last 4H swing low before the sweep;
               "lookback" = lowest low of the last LEG_LOOKBACK 4H candles).
       4H FVG  REQUIRE_4H_FVG: a bullish 4H FVG formed by that leg into the sweep (middle candle at or before the
               sweep candle), not closed through before the sweep. It does not have to be inverted.
    3. 1H FVG  bullish 1H FVGs formed by the same leg into the sweep (candle 1 at or after the start of the 4H leg,
               middle candle at or before the 1H sweep candle), still intact at the sweep.
       INVERSION  within H1_INVERT_WINDOW 1H candles after the sweep, a 1H candle CLOSES below one of them, with
               displacement (structure.displacement on 1H: >= 2 candles, >= 1 ATR) and an MSS / break of
               structure on 1H (close below the last confirmed 1H swing low before the sweep extreme,
               structure.MSS_PIVOT each side), both confirmed by the inversion candle's close.
    -> 1H IFVG signal at the close of that candle. Invalidation level = sweep extreme.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ifvg
import structure
from swings import TEST_START, add_break_times, build_htf, find_swings

REQUIRE_4H_FVG = True
H1_INVERT_WINDOW = 20          # 1H candles after the sweep in which the 1H FVG must be inverted
REQUIRE = "MSS"                # "MSS" (rule 3) | "CISD or MSS"
H1 = pd.Timedelta(hours=1)
LEVEL_FILTER = None            # optional callable(levels, h1) -> levels


def build_setups(h1: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    htf = {tf: build_htf(h1, tf) for tf in ("D", "W", "M", "4H")}
    htf["1H"] = h1.assign(Start=h1.index, End=h1.index + H1)          # rule 1c: 1H swing liquidity
    h4_full = htf["4H"]
    h4 = h4_full.drop(columns=["Start", "End"])
    levels = pd.concat([find_swings(htf[tf], tf) for tf in ifvg.SWEEP_TFS], ignore_index=True)
    levels = levels[levels["tf"].isin(ifvg.SWEEP_TFS)]
    levels = add_break_times(levels, h1)
    levels = levels[levels["broken_time"].notna() & (levels["broken_time"] >= max(TEST_START, h1.index[0]))]
    if LEVEL_FILTER is not None:                       # e.g. setups_4hsweep.poi_filter (rule 1b / 1c POI)
        levels = LEVEL_FILTER(levels, h1)

    o4, hh4, ll4, c4 = (h4[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    h, l, c = h1["High"].to_numpy(), h1["Low"].to_numpy(), h1["Close"].to_numpy()
    idx1, n1 = h1.index, len(h1)
    f4, f1 = ifvg.find_fvgs(h4), ifvg.find_fvgs(h1)
    out: dict[tuple, dict] = {}
    for lv in levels.sort_values("broken_time").itertuples(index=False):
        short = lv.type == "high"
        want = "bull" if short else "bear"
        s1 = idx1.get_indexer([lv.broken_time])[0]
        s4 = h4.index.searchsorted(lv.broken_time, side="right") - 1
        if s1 < 0 or s4 < 0:
            continue
        # ---- rule 2: the 4H leg into the sweep and its 4H FVG
        origin4 = ifvg.leg_origin(o4, hh4, ll4, c4, s4, short)
        if origin4 < 0:
            continue
        fv4 = f4[(f4["dir"] == want) & (f4["idx"] - 2 >= origin4) & (f4["idx"] - 1 <= s4)
                 & ((f4["inv_idx"] < 0) | (f4["inv_idx"] >= s4))]
        if REQUIRE_4H_FVG and fv4.empty:
            continue
        leg_start = h4.index[origin4]
        # ---- rule 3: 1H FVGs of the same leg, inverted with displacement + MSS
        j_max = min(s1 + H1_INVERT_WINDOW, n1 - 1)
        fv1 = f1[(f1["dir"] == want) & (idx1[np.maximum(f1["idx"].to_numpy() - 2, 0)] >= leg_start)
                 & (f1["idx"] - 1 <= s1) & (f1["inv_idx"] >= s1) & (f1["inv_idx"] <= j_max)
                 & (f1["inv_idx"] > f1["idx"])]
        fv1 = fv1.sort_values(["inv_idx", "bottom" if short else "top"], ascending=[True, short])
        chosen = None
        for f in fv1.itertuples(index=False):
            j = int(f.inv_idx)
            ok_d, run_len, move, _ = structure.displacement(h1, j, short)
            q = structure.quality(h1, {"inv_idx": j}, s1, want)
            mss_ok = pd.notna(q["mss_time"])
            conf_ok = mss_ok if REQUIRE == "MSS" else (mss_ok or pd.notna(q["cisd_time"]))
            if ok_d and conf_ok:
                chosen = (f, j, run_len, move, q)
                break
        if chosen is None:
            continue
        f, j, run_len, move, q = chosen
        key = (int(f.idx), j, want)
        tag = f"{lv.tf}{'H' if short else 'L'} {lv.price:.2f}"
        if key in out:
            if tag not in out[key]["swept_levels"]:
                out[key]["swept_levels"] += f", {tag}"
            continue
        ext_i = s1 + int(np.argmax(h[s1:j + 1]) if short else np.argmin(l[s1:j + 1]))
        f4row = fv4.sort_values("idx").iloc[-1] if len(fv4) else None
        atr_j = structure._arrays(h1)[4][j]
        r5 = {"status": "signal", "retest_time": idx1[s1], "h1_fvg_time": idx1[int(f.idx) - 2],
              "h1_fvg_bottom": f.bottom, "h1_fvg_top": f.top, "h1_signal_time": idx1[j] + H1,
              "h1_signal_close": c[j], "h1_disp_candles": run_len, "h1_disp_atr": round(move / atr_j, 2),
              "x": {"anchor": ext_i, "extreme": h[ext_i] if short else l[ext_i], "inval": n1, "retest": s1,
                    "origin": s1, "fvg_idx": int(f.idx), "inv_idx": j, "n_candidates": len(fv1)}}
        out[key] = {
            "tf": "1H", "signal": "short" if short else "long", "swept_levels": tag, "sweep_time": lv.broken_time,
            "signal_time": idx1[j] + H1, "extreme_time": idx1[ext_i],
            "fvg_bottom": f4row["bottom"] if f4row is not None else f.bottom,      # 4H FVG of the leg (reference)
            "fvg_top": f4row["top"] if f4row is not None else f.top,
            "confirm": "MSS" + ("+CISD" if pd.notna(q["cisd_time"]) else ""),
            "disp_candles": run_len, "disp_atr": round(move / atr_j, 2), "mss_level": q["mss_level"],
            "leg_start": leg_start, "x_sweep_idx": s1, "x_inv_idx": j, "x_fvg_idx": int(f.idx), "r5": r5,
        }
    setups = sorted(out.values(), key=lambda d: d["signal_time"])
    return h4, setups
