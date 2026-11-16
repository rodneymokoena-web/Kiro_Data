"""Intraday 5m path: 5m sweep -> 5m FVG of the leg inverted by a 5m close -> 5m IFVG signal -> retest + 5m entry (rule 6).
SHORT described; LONG mirrored.

    SWEEP       a Rule 1 level (intraday liquidity) swept on 5m candles (swings.add_break_times_5m), pinned to the 5m candle that
                confirms the sweep.
    LEG         from the last confirmed 5m swing low (ifvg.LEG_PIVOT = 2 each side) before the sweep candle.
    5m FVG      a bullish 5m FVG of that leg, formed INTO the sweep (middle candle at or before the sweep candle), not closed below
                before the sweep.
    INVERSION   within INVERT_5M (5) 5m candles, a 5m CLOSE below it (earliest inversion wins), with
                5m displacement (>= DISP_5M consecutive bearish candles moving >= 1 ATR14) and a 5m MSS (a close below the last
                confirmed 5m swing low before the sweep extreme, by the inversion candle).
    RETEST      a 5m candle high (short) / low (long) reaches the 5m IFVG within RETEST_5M (30 min) after the inversion close; cancelled if price trades beyond the sweep extreme first.
    TRIGGER     within TRIGGER_5M (30 min) of the retest: a 15m CISD or a 5m MSS, with displacement.
    ENTRY       limit at the near edge of the 5m MSS FVG or 5m volume imbalance after the trigger (entry_ltf.with_volume_imbalances),
                valid FILL_5M (30 min); cancelled by a 5m close back through that zone (unless the next 5m candle re-inverts it).
    STOP        the high of the last COMPLETED bearish 5m candle (at the fill) whose open AND close are above the entry, + 2 points
                (long: low of the last bullish 5m candle opening and closing below the entry, - 2); none within 48 candles = no trade.
    -> target 3R, breakeven at +1R.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import ifvg
import structure
import swings as S

INVERT_5M = int(__import__("os").environ.get("INVERT_5M", "5"))   # 5m candles after the sweep for the 5m inversion
RETEST_5M = pd.Timedelta(minutes=int(__import__('os').environ.get('RETEST_5M_MIN', '30')))   # a 5m candle must retest the 5m IFVG within this time after the inversion close
DISP_5M = 2
TRIGGER_5M = pd.Timedelta(minutes=30)   # 15m CISD / 5m MSS within this time after the 5m IFVG retest
FILL_5M = pd.Timedelta(minutes=30)      # entry limit valid this long after the trigger
M5 = pd.Timedelta(minutes=5)


def _levels(h1: pd.DataFrame) -> pd.DataFrame:
    """Intraday Rule 1 levels (same set as ifvg_1h.build_4h_setups_v1)."""
    import ifvg_1h
    htf = {tf: S.build_htf(h1, tf) for tf in ("D", "W", "M", "4H")}
    f1 = h1.assign(Start=h1.index, End=h1.index + pd.Timedelta(hours=1))
    htf["1H"] = f1
    parts = []
    for tf in ifvg.SWEEP_TFS:
        if tf == "1H":
            saved = S.PIVOT_BY_TF.get("1H")
            S.PIVOT_BY_TF["1H"] = ifvg.RULE1_4H_PIVOT
            try:
                parts.append(S.find_swings(htf[tf], tf))
            finally:
                if saved is None:
                    S.PIVOT_BY_TF.pop("1H", None)
                else:
                    S.PIVOT_BY_TF["1H"] = saved
        else:
            parts.append(S.find_swings(htf[tf], tf))
    if ifvg.SESSION_TFS:
        parts.append(S.session_levels(h1, ifvg.SESSION_TFS))
    if ifvg.FVG_LIQ:
        parts.append(S.fvg_far_edge_levels(htf["4H"]))
        if ifvg_1h.FVG_LIQ_1H:
            parts.append(S.fvg_far_edge_levels(f1, "1HFVG"))
    return pd.concat(parts, ignore_index=True)


def build_setups(h1: pd.DataFrame, m5: pd.DataFrame) -> list[dict]:
    bars = m5[["Open", "High", "Low", "Close"]]
    levels = S.add_break_times_5m(_levels(h1), bars, None)
    o, h, l, c = (bars[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx, n = bars.index, len(bars)
    atr = structure._arrays(bars)[4]

    def accept(b, fvg, s, fvg_dir):
        short = fvg_dir == "bull"
        j = int(fvg["inv_idx"])
        ok_d, run_len, move, _ = structure.displacement(b, j, short)
        ok_m, mlv, mi = structure.mss(b, s, j, short, "ext")
        ok = bool(ok_d and ok_m and mi <= j)
        return {"passed": ok, "confirm": "5m MSS" if ok_m else "-", "disp_candles": int(run_len),
                "disp_atr": round(float(move / atr[j]), 2) if atr[j] else 0.0,
                "reject_reason": "" if ok else ("no 5m displacement" if not ok_d else "no 5m MSS")}

    saved = (ifvg.INVERT_WINDOW, structure.DISP_MIN_CANDLES, ifvg.LEG_MODE, ifvg.FVG_SELECT, ifvg.FVG_INTO_SWEEP)
    ifvg.INVERT_WINDOW, structure.DISP_MIN_CANDLES = INVERT_5M, DISP_5M
    ifvg.LEG_MODE, ifvg.FVG_SELECT, ifvg.FVG_INTO_SWEEP = "swing", "first", True
    try:
        st = ifvg.find_setups(bars, levels, "5m", accept=accept)
    finally:
        ifvg.INVERT_WINDOW, structure.DISP_MIN_CANDLES, ifvg.LEG_MODE, ifvg.FVG_SELECT, ifvg.FVG_INTO_SWEEP = saved
    out = []
    for r in st.to_dict("records") if len(st) else []:
        short = r["signal"] == "short"
        s, j = int(r["x_sweep_idx"]), int(r["x_inv_idx"])
        ext = s + int(np.argmax(h[s:j + 1]) if short else np.argmin(l[s:j + 1]))
        sig_t = idx[j] + M5
        r5 = {"status": "signal", "retest_time": idx[s], "h1_fvg_time": idx[int(r["x_fvg_idx"]) - 2],
              "h1_fvg_bottom": r["fvg_bottom"], "h1_fvg_top": r["fvg_top"], "h1_signal_time": sig_t,
              "h1_signal_close": c[j], "h1_disp_candles": r.get("disp_candles", 0), "h1_disp_atr": r.get("disp_atr", 0.0),
              "x": {"anchor": ext, "extreme": h[ext] if short else l[ext], "inval": n, "retest": s, "origin": s,
                    "fvg_idx": int(r["x_fvg_idx"]), "inv_idx": j, "n_candidates": 1}}
        out.append({"tf": "5m", "signal": r["signal"], "swept_levels": r["swept_levels"], "sweep_time": r["sweep_time"],
                    "signal_time": sig_t, "extreme_time": idx[ext], "fvg_bottom": r["fvg_bottom"], "fvg_top": r["fvg_top"],
                    "confirm": "5m IFVG + 5m MSS", "disp_candles": r.get("disp_candles", 0), "disp_atr": r.get("disp_atr", 0.0),
                    "x_sweep_idx": s, "x_inv_idx": j, "x_fvg_idx": int(r["x_fvg_idx"]), "r5": r5, "fast5": True})
    return sorted(out, key=lambda d: d["signal_time"])
