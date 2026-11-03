"""Swing model as in the user's chart (US100 1H, 29 Oct 2026 short). SHORT described; LONG is the mirror image.

    Rules 1-3   unchanged: D/W/M swing high swept -> 4H FVG of the leg -> 4H inversion (M1: 4H displacement + 1H MSS).
    ENTRY       Rule 4 retest IS the entry: SELL LIMIT at the BOTTOM of the 4H IFVG, live from the 4H signal for
                RETEST_WINDOW (48h). Cancelled if a 1H candle opens above the sweep extreme before the fill
                (rule 4 cancellation). No 1H IFVG step.
    STOP        STOP_KIND:
                "1H OB above 1H FVG" (chart): sweeping leg on 1H = lowest low after the last 4H swing low before the
                    sweep -> 1H sweep extreme. 1H FVG above the 4H IFVG = the bullish 1H FVG of that leg whose TOP is
                    above the 4H IFVG top (it may overlap the IFVG), the lowest such. 1H OB (OB_PICK): "nearest" = the
                    order block of the leg nearest above that FVG (its high above the FVG top); "last" = the last order
                    block of the leg before the sweep extreme whose high is above the FVG top. Stop above the OB high.
                    No such FVG -> the OB nearest above the 4H IFVG top; no OB -> the 4H order block.
                "1H OB above 4H IFVG": the order block of the leg nearest above the 4H IFVG top.
                "4H OB disp" / "4H extreme": as in swing.py.
                OB_TYPE "bull" = down-close 1H candle followed within 3 candles by a close above its high (the OBs
                of a leg up); "bear" = up-close candle followed by a close below its low.
    TARGET      "3R" or "D/W liquidity" (nearest unbroken D/W swing low below the entry).
    MANAGEMENT  breakeven at +1R, same candle stop + target -> stop (swing.simulate).
"""
from __future__ import annotations

import contextlib
import io

import numpy as np
import pandas as pd

import ifvg
import stops_ext
import swing as W
from backtest import COST, SL_BUFFER
from ifvg_1h import RETEST_WINDOW
from ote import H4
from swings import DATA, SYMBOLS, add_break_times, build_htf, find_swings, load

STOP_KIND = "1H OB of drop FVG"   # snapshot rules (snapshot 1 version: "1H OB above 1H FVG")
# Snapshot-2 rules (SETUPS="1H close"): rule 2 = LAST 4H FVG of the sweeping leg; rule 3 = first 1H CLOSE through it
# after the sweep, 1H MSS (swing before the extreme) + 1H displacement of >= DISP_MIN_1H candles (>= 1 ATR).
# STOP_KIND "1H OB of drop FVG": the first BEARISH 1H FVG formed by the drop from the sweep extreme (candle 3 after the
#   extreme, complete before the fill, top above the 4H IFVG bottom); OB = its candle 1 (the last up-close 1H candle
#   before the drop; if candle 1 is not up-close, the last up-close candle up to 3 before it). Stop above OB_LEVEL:
#   "touch" (near edge = OB low for a short), "50%" (middle of the OB candle) or "high". None -> the sweep extreme.
# TARGET "1H swing low": the most recent confirmed 1H swing low (2 candles each side) before the 4H FVG's middle candle
#   = where the leg that created the 4H FVG started.
SETUPS = "1H close"     # "1H close" (snapshot rules) | "M1" (current rules 2-3)
# Rule 1b: 4H swing sweeps -> 1H FVG -> 1H IFVG (setups_4hsweep.py), traded with the same entry / stop / target rules.
# 0 = off (D/W/M only); N = 4H swings with N candles each side.
SWING_4H_PIVOT = 0
SWING_1H_PIVOT = 0      # rule 1c: 1H swing sweeps -> 1H FVG -> 1H IFVG (0 = off)
DISP_MIN_1H = 1
OB_LEVEL = "50%"        # stop above the middle of the 1H OB (chosen; "touch" / "high" tested)
OB_TYPE = "bull"
OB_PICK = "nearest"     # "nearest" = OB nearest above the 1H FVG; "last" = last OB of the leg before the sweep extreme
TARGET = "1H swing low"


def _anchor(st: dict, h1: pd.DataFrame) -> int:
    short = st["signal"] == "short"
    idx = h1.index
    a0 = idx.searchsorted(st["extreme_time"])
    a1 = max(a0 + 1, idx.searchsorted(st["extreme_time"] + st.get("extreme_span", H4)))
    seg = h1["High"].to_numpy()[a0:a1] if short else h1["Low"].to_numpy()[a0:a1]
    return a0 + int(np.argmax(seg) if short else np.argmin(seg))


def _ob_last(h1: pd.DataFrame, a: int, b: int, bull: bool, short: bool, ref: float) -> float:
    """Last order block in h1[a..b] (counting back from b) whose high (short) is above ref."""
    o, h, l, c = (h1[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    for i in range(b - 1, max(a, 0) - 1, -1):
        up, dn = c[i] > o[i], c[i] < o[i]
        nxt = c[i + 1:min(i + 1 + stops_ext.OB_BREAK, b + 1)]
        if bull:
            ok = (dn and (nxt > h[i]).any()) if short else (up and (nxt < l[i]).any())
        else:
            ok = (up and (nxt < l[i]).any()) if short else (dn and (nxt > h[i]).any())
        lv = h[i] if short else l[i]
        if ok and ((short and lv > ref) or (not short and lv < ref)):
            return float(lv)
    return np.nan


def stop_level(kind: str, st: dict, h1: pd.DataFrame, h1_fvgs: pd.DataFrame, h4: pd.DataFrame, anchor: int,
               ob_type: str = OB_TYPE, ob_pick: str = OB_PICK) -> tuple[float, str]:
    """Stop level before the buffer and a tag describing where it came from."""
    short = st["signal"] == "short"
    if kind in ("4H OB disp", "4H OB leg"):
        return stops_ext.level(kind, st, {}, h1_fvgs, h4), kind
    if kind == "4H extreme":
        return float(h1["High"].iat[anchor] if short else h1["Low"].iat[anchor]), kind
    a = stops_ext._leg_start_1h(st, {"x": {"anchor": anchor}}, h1, h4)
    bull = ob_type == "bull"
    find = _ob_last if ob_pick == "last" else stops_ext._ob_window
    edge4 = st["fvg_top"] if short else st["fvg_bottom"]           # far edge of the 4H IFVG
    if kind == "1H OB above 1H FVG":
        f = h1_fvgs[(h1_fvgs["dir"] == ("bull" if short else "bear")) & (h1_fvgs["idx"] - 2 >= a)
                    & (h1_fvgs["idx"] <= anchor)]
        f = f[f["top"] > edge4] if short else f[f["bottom"] < edge4]
        if len(f):
            row = f.loc[f["top"].idxmin()] if short else f.loc[f["bottom"].idxmax()]
            ref = row["top"] if short else row["bottom"]                # OB must reach beyond this FVG
            lv = find(h1, a, anchor, bull, short, ref)
            if not np.isnan(lv):
                return lv, "1H OB above 1H FVG"
        lv = find(h1, a, anchor, bull, short, edge4)
        if not np.isnan(lv):
            return lv, "1H OB above 4H IFVG (no 1H FVG)"
        return stops_ext.level("4H OB disp", st, {}, h1_fvgs, h4), "4H OB (no 1H OB)"
    if kind == "1H OB above 4H IFVG":
        lv = stops_ext._ob_window(h1, a, anchor, bull, short, edge4)
        if not np.isnan(lv):
            return lv, kind
        return stops_ext.level("4H OB disp", st, {}, h1_fvgs, h4), "4H OB (no 1H OB)"
    raise ValueError(kind)


def _setups_1h_close(h1: pd.DataFrame, disp_min: int):
    import setups_v3 as V3
    import structure
    keys = ("INVERT_ON", "WICK_CLOSE", "CISD_MODE", "REQUIRE", "WAIT_1H", "MSS_MODE")
    saved = {k: getattr(V3, k) for k in keys}
    saved2 = (ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK, structure.DISP_MIN_CANDLES)
    for k, v in zip(keys, ("close", "any", "1h_close", "mss", 0, "ext")):
        setattr(V3, k, v)
    ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK, structure.DISP_MIN_CANDLES = "any", 60, disp_min
    try:
        return V3.build_setups(h1)
    finally:
        for k, v in saved.items():
            setattr(V3, k, v)
        ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK, structure.DISP_MIN_CANDLES = saved2


def _drop_ob(st: dict, h1: pd.DataFrame, h1_fvgs: pd.DataFrame, anchor: int, q: int, ob_level: str) -> tuple[float, str]:
    short = st["signal"] == "short"
    o, h, l, c = (h1[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    f = h1_fvgs[(h1_fvgs["dir"] == ("bear" if short else "bull")) & (h1_fvgs["idx"] > anchor) & (h1_fvgs["idx"] < q)
                & (h1_fvgs["idx"] - 2 >= anchor - 1)]
    f = f[f["top"] > st["fvg_bottom"]] if short else f[f["bottom"] < st["fvg_top"]]
    if f.empty:
        return float(h[anchor] if short else l[anchor]), "sweep extreme (no 1H FVG of the drop)"
    c1 = int(f.sort_values("idx").iloc[0]["idx"]) - 2
    for i in range(c1, max(c1 - 4, -1), -1):
        if (short and c[i] > o[i]) or (not short and c[i] < o[i]):
            if ob_level == "high":                  # far edge of the OB
                lv = h[i] if short else l[i]
            elif ob_level == "touch":               # near edge (first touched from the entry side)
                lv = l[i] if short else h[i]
            else:                                   # "50%"
                lv = (h[i] + l[i]) / 2
            return float(lv), "1H OB of drop FVG"
    return float(h[anchor] if short else l[anchor]), "sweep extreme (no up-close OB)"


def _swing_low_target(st: dict, h1: pd.DataFrame, h4: pd.DataFrame, q: int) -> float:
    """Most recent confirmed 1H swing low (short) before the 4H FVG's middle candle."""
    short = st["signal"] == "short"
    h, l = h1["High"].to_numpy(), h1["Low"].to_numpy()
    mid = (h1 if st.get("fvg_tf") == "1H" else h4).index[int(st["x_fvg_idx"]) - 1]
    b = int(h1.index.searchsorted(mid))
    p = 2
    for i in range(b - 1, p - 1, -1):
        if i + p >= b + 0 and i + p > q:
            continue
        w = l[i - p:i + p + 1] if short else h[i - p:i + p + 1]
        if (short and l[i] == w.min()) or (not short and h[i] == w.max()):
            return float(l[i] if short else h[i])
    return np.nan


def run(stop_kind: str = STOP_KIND, ob_type: str = OB_TYPE, target: str = TARGET, ob_pick: str = OB_PICK,
        setups_kind: str = SETUPS, disp_min: int = DISP_MIN_1H, ob_level: str = OB_LEVEL,
        swing_4h_pivot: int | None = None, swing_1h_pivot: int | None = None) -> pd.DataFrame:
    if swing_4h_pivot is None:
        swing_4h_pivot = SWING_4H_PIVOT
    if swing_1h_pivot is None:
        swing_1h_pivot = SWING_1H_PIVOT
    trades = []
    for symbol, (h1_file, _, _) in SYMBOLS.items():
        h1 = load(DATA / h1_file)
        htf = {tf: build_htf(h1, tf) for tf in ("D", "W", "M")}
        levels = add_break_times(pd.concat([find_swings(htf[tf], tf) for tf in ("M", "W", "D")], ignore_index=True), h1)
        with contextlib.redirect_stdout(io.StringIO()):
            h4, setups = W._swing_setups(h1) if setups_kind == "M1" else _setups_1h_close(h1, disp_min)
            if swing_4h_pivot > 0 or swing_1h_pivot > 0:
                import setups_4hsweep
                extra = setups_4hsweep.swing_setups(h1, swing_4h_pivot, "4H") if swing_4h_pivot > 0 else []
                extra += setups_4hsweep.swing_setups(h1, swing_1h_pivot, "1H") if swing_1h_pivot > 0 else []
                seen, merged = set(), []
                for st in sorted(setups + extra, key=lambda d: d["signal_time"]):
                    k = (st["signal"], round(float(st["fvg_bottom"]), 4), round(float(st["fvg_top"]), 4))
                    if k not in seen:                   # same 1H IFVG from a 4H and a 1H sweep -> once
                        seen.add(k)
                        merged.append(st)
                setups = merged
        h1_fvgs = ifvg.find_fvgs(h1)
        o, h, l = (h1[k].to_numpy() for k in ("Open", "High", "Low"))
        idx, n = h1.index, len(h1)
        for k_st, st in enumerate(setups, 1):
            short = st["signal"] == "short"
            anchor = _anchor(st, h1)
            extreme = h[anchor] if short else l[anchor]
            level = st["fvg_bottom"] if short else st["fvg_top"]
            q0, q1 = idx.searchsorted(st["signal_time"]), min(idx.searchsorted(st["signal_time"] + RETEST_WINDOW), n)
            q, entry = -1, np.nan
            for i in range(q0, q1):
                if (short and o[i] > extreme) or (not short and o[i] < extreme):
                    break                                               # rule 4 cancellation
                if (short and h[i] >= level) or (not short and l[i] <= level):
                    q, entry = i, (max(level, o[i]) if short else min(level, o[i]))
                    break
            if q < 0:
                continue
            if stop_kind == "1H OB of drop FVG":
                base, tag = _drop_ob(st, h1, h1_fvgs, anchor, q, ob_level)
            else:
                base, tag = stop_level(stop_kind, st, h1, h1_fvgs, h4, anchor, ob_type, ob_pick)
            if np.isnan(base):
                continue
            sl = base + SL_BUFFER[symbol] if short else base - SL_BUFFER[symbol]
            if (short and sl <= entry) or (not short and sl >= entry):
                continue
            risk = abs(entry - sl)
            if target == "3R":
                tp, ttag = (entry - 3 * risk if short else entry + 3 * risk), "3R"
            elif target == "1H swing low":
                tp, ttag = _swing_low_target(st, h1, h4, q), "1H swing low"
                if np.isnan(tp) or (short and tp >= entry) or (not short and tp <= entry):
                    continue
            else:
                tp, ttag = W.pick_target(levels, short, entry, idx[q])
                if np.isnan(tp):
                    continue
            sim = W.simulate(h1, q, short, entry, sl, tp)
            pnl = (entry - sim["price"]) if short else (sim["price"] - entry)
            trades.append({"symbol": symbol, "setup": k_st, "signal": st["signal"], "swept": st["swept_levels"],
                           "4h_signal_time": st["signal_time"], "4h_ifvg_bottom": st["fvg_bottom"],
                           "4h_ifvg_top": st["fvg_top"], "extreme": extreme, "entry_time": idx[q], "entry": entry,
                           "stop": sl, "stop_from": tag, "target": tp, "target_level": ttag, "risk_pts": risk,
                           "planned_rr": abs(tp - entry) / risk, "exit": sim["exit"], "exit_time": idx[sim["k"]],
                           "exit_price": sim["price"], "pnl_pts": pnl, "r_net": (pnl - COST[symbol]) / risk})
    return pd.DataFrame(trades)


if __name__ == "__main__":
    t = run()
    pd.set_option("display.width", 250)
    print(t.to_string(index=False) if len(t) else "no trades")
