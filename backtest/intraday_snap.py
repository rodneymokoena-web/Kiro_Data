"""Intraday model (snapshot rules, 5m): sweep -> 5m IFVG + 5m break of structure -> limit at the 5m FVG of the displacement.
SHORT described; LONG is the mirror image. Rule 1 liquidity = the intraday levels (setups_5m._levels).

    2 SWEEP      (swings.add_break_times_5m, SWEEP5M_MODE "ab12")
                 (A) a 5m candle wicks above a Rule 1 swing and closes back below it, or
                 (B) one or two 5m candles close above it, immediately followed by two strong bearish displacement 5m candles
                     (together >= 1 ATR14), the second closing below the low of the first sweeping candle.
                 The first sweep event uses the level up. s = the 5m candle that confirms the sweep.
    3 LEG        origin (break-of-structure level) = the lowest low between the previous 5m swing high (LEG_PIVOT = 2 candles each
                 side, formed before the sweep extreme) and the sweep extreme = where the leg into the sweep started.
                 The 5m FVG to invert = the intact bullish 5m FVG nearest below the sweep (highest bottom) among those completed in the
                 IFVG_LOOKBACK_5M 5m candles before the sweep candle; intact = no 5m close below its bottom before the sweep.
                 The 5m order block (-> breaker) = the last bearish 5m candle at or before the origin (up to OB_LOOKBACK candles back).
    LIQUIDITY+   (MACRO_LIQ) the high / low of every completed ICT macro window (MACROS, New York time), valid MACRO_VALID.
    IFVG         (IFVG_15M) a 5m or a 15m FVG.
    BREAK        a 5m close - or (BOS_WICK) a 5m wick - below the leg origin low, or (MSS_BOS) below the last 5m swing low formed
                 after the sweep extreme;
                 the breaker is the last bearish candle at or before the low that was broken.
    4 REVERSAL   within REVERSAL_5M 5m candles of the sweep: 5m closes below the FVG's bottom (5m IFVG) AND below the origin low
                 (5m break of structure); the candle completing the second of the two needs 5m displacement: >= DISP_5M bearish
                 candles moving >= 1 ATR14, or a single bearish candle whose body is >= 1 ATR14.
    5 ENTRY      the bearish 5m FVG or 5m volume imbalance (entry_ltf.volume_imbalances) formed in the drop from the sweep extreme
                 to the reversal candle (first candle at/after the extreme, completed up to FVG_AFTER candles after the reversal close;
                 the latest one = closest to the reversal).
                 Sell limit at its near edge (bottom), live from the candle after it completes, valid ENTRY_VALID after the reversal
                 close. Cancelled if a candle opens above the stop before the fill.
    6 STOP       the high of the 5m breaker (order block), no buffer. Must be above the entry, else no trade.
    BIAS         (BIAS_FILTER) the most recent sweep of a Rule 1 SWING level (D / W / M / 4H / 1H swings, same 5m sweep rule) sets the
                 bias: a swing HIGH swept = bearish, a swing LOW swept = bullish. A setup is only taken in the direction of the bias at
                 its reversal candle (session levels and FVG edges do not change the bias).
    6b FILTERS   no minimum stop (MIN_STOP_PTS = 0, experiments only). ONE_PER_ENTRY: several setups with
                 the same direction and entry zone / limit price -> one trade (the first signal).
    7 TARGET     TARGET_MODE "R" = TARGET_R x risk; "swing" = the nearest confirmed major 5m swing low (MAJOR_PIVOT candles each side,
                 confirmed before the fill) below the entry, else TARGET_R x risk. Breakeven at +1R (backtest.BE_AT_R).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

import ifvg
import structure
import swings as S

REVERSAL_5M = int(os.environ.get("REVERSAL_5M", "48"))      # N: 5m candles allowed between the sweep and the reversal
ENTRY_VALID = pd.Timedelta(minutes=int(os.environ.get("ENTRY_VALID_MIN", "60")))
TARGET_MODE = os.environ.get("TARGET_5M", "R")             # "R" = fixed R | "swing" = major 5m swing (fallback fixed R)
TARGET_R = float(os.environ.get("TARGET_R_5M", "3"))
BIAS_FILTER = os.environ.get("BIAS_5M", "1") == "1"        # only trade in the direction of the last Rule 1 swing sweep
BIAS_TFS = ("D", "W", "M", "4H", "1H")                     # Rule 1 swing levels that set the bias
IFVG_15M = os.environ.get("IFVG_15M", "1") == "1"         # the IFVG may be a 5m OR a 15m FVG
MSS_BOS = os.environ.get("MSS_BOS", "1") == "1"           # the break may also be a post-sweep 5m MSS (close below the last 5m swing low after the extreme)
MIN_STOP = float(os.environ.get("MIN_STOP_PTS", "0"))     # removed (0 = no minimum stop); kept only for experiments
ONE_PER_ENTRY = os.environ.get("ONE_PER_ENTRY", "1") == "1"   # one trade per direction + entry zone/price (first signal wins)
BOS_WICK = os.environ.get("BOS_WICK", "1") == "1"         # the break may be a body close OR a wick through the level (0 = close only)
MACRO_LIQ = os.environ.get("MACRO_LIQ", "1") == "1"       # ICT macro-time highs/lows as Rule 1 liquidity
MACRO_VALID = pd.Timedelta(hours=float(os.environ.get("MACRO_VALID_H", "24")))
# ICT macro windows, New York time (start, end); the high and low of each completed window are liquidity levels (tf "MACRO")
MACROS = (("02:33", "03:00"), ("04:03", "04:30"), ("08:50", "09:10"), ("09:50", "10:10"), ("10:50", "11:10"),
          ("11:50", "12:10"), ("13:10", "13:40"), ("15:15", "15:45"), ("19:50", "20:10"), ("20:50", "21:10"))
MAJOR_PIVOT = 10                                            # major 5m swing: candles each side
LEG_PIVOT = 2
DISP_5M = 2
OB_LOOKBACK = 10
FVG_AFTER = 2
IFVG_LOOKBACK_5M = int(os.environ.get("IFVG_LOOKBACK_5M", "48"))   # bullish 5m FVGs completed in this many 5m candles before the sweep
M5 = pd.Timedelta(minutes=5)


def _major_swing(h, l, q, short, entry):
    """Nearest confirmed major 5m swing low (short) below the entry / high (long) above it, confirmed by candle q-1."""
    p = MAJOR_PIVOT
    best = np.nan
    for i in range(q - 1 - p, p - 1, -1):
        if short and l[i] == l[i - p:i + p + 1].min() and l[i] < entry:
            if np.isnan(best) or l[i] > best:
                best = l[i]
        if (not short) and h[i] == h[i - p:i + p + 1].max() and h[i] > entry:
            if np.isnan(best) or h[i] < best:
                best = h[i]
        if q - 1 - i > 2000:
            break
    return best


def macro_levels(m5: pd.DataFrame) -> pd.DataFrame:
    """High and low of every completed ICT macro window (MACROS, New York time) on the 5m candles. Usable from the window end,
    sweepable until MACRO_VALID after it."""
    ny = m5.index.tz_convert("America/New_York")
    mins = ny.hour * 60 + ny.minute
    day = ny.normalize()
    rows = []
    for a, b in MACROS:
        sa = int(a[:2]) * 60 + int(a[3:]); sb = int(b[:2]) * 60 + int(b[3:])
        sa5 = sa - sa % 5                                       # the 5m candle containing the window start
        inb = (mins >= sa5) & (mins < sb)
        if not inb.any():
            continue
        sub = m5[inb].assign(_d=day[inb])
        g = sub.groupby("_d")
        for d, hi, lo in zip(g["High"].max().index, g["High"].max().to_numpy(), g["Low"].min().to_numpy()):
            end = (d + pd.Timedelta(minutes=sb)).tz_convert("UTC")
            for kind, price in (("high", float(hi)), ("low", float(lo))):
                rows.append({"tf": "MACRO", "type": kind, "price": price, "pivot_time": end, "confirmed_time": end,
                             "expires": end + MACRO_VALID})
    return pd.DataFrame(rows, columns=["tf", "type", "price", "pivot_time", "confirmed_time", "expires"])


def _fvgs_5m_15m(bars: pd.DataFrame, fv5: pd.DataFrame) -> pd.DataFrame:
    """5m FVGs plus 15m FVGs (15m candles built from the 5m candles), all indexed by the 5m candle at whose close they complete."""
    out = fv5.assign(tf="5m")[["dir", "idx", "bottom", "top", "tf"]]
    if not IFVG_15M:
        return out
    m15 = bars.resample("15min", label="left", closed="left").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    f15 = ifvg.find_fvgs(m15)
    if f15.empty:
        return out
    end15 = m15.index[f15["idx"].to_numpy()] + pd.Timedelta(minutes=15)
    i5 = bars.index.searchsorted(end15) - 1                     # the last 5m candle of the 15m candle 3
    f = f15.assign(idx=i5, tf="15m")[["dir", "idx", "bottom", "top", "tf"]]
    return pd.concat([out, f[f["idx"] >= 0]], ignore_index=True)


def build_trades(h1: pd.DataFrame, m5: pd.DataFrame, symbol: str = "US100") -> pd.DataFrame:
    import backtest as B
    import setups_5m
    bars = m5[["Open", "High", "Low", "Close"]]
    o, h, l, c = (bars[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx, n = bars.index, len(bars)
    lv0 = setups_5m._levels(h1)
    if MACRO_LIQ:
        lv0 = pd.concat([lv0, macro_levels(bars)], ignore_index=True)
    levels = S.add_break_times_5m(lv0, bars, None)
    levels = levels[levels["broken_time"].notna() & (levels["broken_time"] >= max(S.TEST_START, idx[0]))]
    # bias timeline: sweeps of Rule 1 swing levels, in time order (+1 = a low swept -> bullish, -1 = a high swept -> bearish)
    bl = levels[levels["tf"].isin(BIAS_TFS)].sort_values("broken_time")
    bias_t = pd.DatetimeIndex(bl["broken_time"]).as_unit("ns")
    bias_v = np.where(bl["type"].to_numpy() == "high", -1, 1)
    fv = ifvg.find_fvgs(bars)
    fvi = _fvgs_5m_15m(bars, fv)                              # IFVG candidates: 5m and (IFVG_15M) 15m FVGs
    import entry_ltf
    zones = entry_ltf.with_volume_imbalances(fv, bars)       # entry zones: FVGs (start = candle 1) + volume imbalances
    atr = structure._arrays(bars)[4]
    saved = (ifvg.LEG_MODE, ifvg.LEG_PIVOT, structure.DISP_MIN_CANDLES)
    ifvg.LEG_MODE, ifvg.LEG_PIVOT, structure.DISP_MIN_CANDLES = "swing", LEG_PIVOT, DISP_5M
    trades, seen = [], set()
    try:
        for lv in levels.sort_values("broken_time").itertuples(index=False):
            short = lv.type == "high"
            s = int(idx.get_indexer([lv.broken_time])[0])
            if s < 0:
                continue
            a0 = max(s - 3, 0)
            ext0 = a0 + int(np.argmax(h[a0:s + 1]) if short else np.argmin(l[a0:s + 1]))     # sweep extreme so far
            # leg origin = lowest low (short) between the previous 5m swing high (2 each side, before the extreme) and the extreme
            p_ = LEG_PIVOT
            ph = -1
            for i in range(ext0 - 1, p_ - 1, -1):
                if i + p_ >= ext0:
                    continue
                w = h[i - p_:i + p_ + 1] if short else l[i - p_:i + p_ + 1]
                if (short and h[i] == w.max()) or (not short and l[i] == w.min()):
                    ph = i
                    break
            if ph < 0:
                continue
            seg = l[ph:ext0 + 1] if short else h[ph:ext0 + 1]
            origin = ph + int(np.argmin(seg) if short else np.argmax(seg))
            # rule 3: bullish FVG of the leg, formed into the sweep, intact at the sweep
            want = "bull" if short else "bear"
            cand = fvi[(fvi["dir"] == want) & (fvi["idx"] < s) & (fvi["idx"] >= s - IFVG_LOOKBACK_5M)]
            f = None
            for r in cand.itertuples(index=False):
                pre = c[int(r.idx) + 1:s]
                if (pre < r.bottom).any() if short else (pre > r.top).any():
                    continue                                          # closed through before the sweep -> not intact
                if f is None or (r.bottom > f.bottom if short else r.top < f.top):
                    f = r                                             # nearest to the sweep
            if f is None:
                continue
            # rule 4: IFVG + break of structure within REVERSAL_5M candles, displacement at the completing candle.
            # Break = a close below the leg origin low, or (MSS_BOS) below the last confirmed 5m swing low formed after the
            # running sweep extreme (a post-sweep market structure shift).
            olow = l[origin] if short else h[origin]
            inv = False
            brk = -1                                                   # index of the low that was broken (origin or MSS low)
            j = -1
            ex = s
            msI = -1
            p_ = LEG_PIVOT
            for t in range(s, min(s + REVERSAL_5M, n - 1) + 1):
                if (short and h[t] > h[ex]) or (not short and l[t] < l[ex]):
                    ex, msI = t, -1
                i = t - 1 - p_
                if MSS_BOS and i > ex:
                    w = l[i - p_:i + p_ + 1] if short else h[i - p_:i + p_ + 1]
                    if (short and l[i] == w.min()) or (not short and h[i] == w.max()):
                        msI = i
                inv = inv or ((c[t] < f.bottom) if short else (c[t] > f.top))
                if brk < 0:
                    bx = (l[t] if short else h[t]) if BOS_WICK else c[t]   # BOS_WICK: a wick through is enough
                    if (bx < olow) if short else (bx > olow):
                        brk = origin
                    elif msI >= 0 and ((bx < l[msI]) if short else (bx > h[msI])):
                        brk = msI
                if inv and brk >= 0:
                    body = (o[t] - c[t]) if short else (c[t] - o[t])
                    if structure.displacement(bars, t, short)[0] or body >= structure.DISP_MIN_ATR * atr[t]:
                        j = t
                    break
            if j < 0:
                continue
            # order block -> breaker: last bearish (short) candle at or before the low that was broken
            ob = -1
            for k in range(brk, max(brk - OB_LOOKBACK, -1), -1):
                if (short and c[k] < o[k]) or (not short and c[k] > o[k]):
                    ob = k
                    break
            if ob < 0:
                continue
            stop = h[ob] if short else l[ob]
            if BIAS_FILTER:                                   # the bias at the reversal candle must match the direction
                k_ = int(bias_t.searchsorted(pd.Timestamp(idx[j]).as_unit("ns"), side="right")) - 1
                if k_ < 0 or bias_v[k_] != (-1 if short else 1):
                    continue
            key = (short, int(f.idx), j)
            if key in seen:
                continue
            seen.add(key)
            a0 = max(s - 3, 0)
            ext = a0 + int(np.argmax(h[a0:j + 1]) if short else np.argmin(l[a0:j + 1]))      # the sweep extreme
            # rule 5: bearish FVG formed in the drop from the sweep extreme to the reversal (latest one)
            ew = "bear" if short else "bull"
            ef = zones[(zones["dir"] == ew) & (zones["start"] >= ext) & (zones["idx"] <= j + FVG_AFTER)]
            if ef.empty:
                continue
            e = ef.sort_values(["idx", "kind"], ascending=[True, False]).iloc[-1]                  # latest zone (FVG preferred over a VI on a tie)
            level = float(e["bottom"] if short else e["top"])
            if (short and stop <= level) or (not short and stop >= level):
                continue
            q0 = max(j, int(e["idx"])) + 1
            q1 = min(int(idx.searchsorted(idx[j] + M5 + ENTRY_VALID)), n)
            q = -1
            for i in range(q0, q1):
                if (short and o[i] > stop) or (not short and o[i] < stop):
                    break
                if (short and h[i] >= level) or (not short and l[i] <= level):
                    q = i
                    break
            if q < 0:
                continue
            entry = max(level, o[q]) if short else min(level, o[q])
            if (short and stop <= entry) or (not short and stop >= entry):
                continue
            risk = abs(entry - stop)
            if risk < MIN_STOP:                               # minimum stop size
                continue
            tp, ttag = (entry - TARGET_R * risk if short else entry + TARGET_R * risk), f"{TARGET_R:g}R"
            if TARGET_MODE == "swing":
                sw = _major_swing(h, l, q, short, entry)
                if not np.isnan(sw):
                    tp, ttag = float(sw), "major 5m swing"
            sim = B.simulate(bars, q, short, entry, stop, tp)
            pnl = (entry - sim["exit_price"]) if short else (sim["exit_price"] - entry)
            trades.append({"symbol": symbol, "signal": "short" if short else "long", "swept": f"{lv.tf} {lv.price:.2f}",
                           "sweep_time": idx[s], "reversal_time": idx[j] + M5, "fvg_bottom": e["bottom"], "fvg_top": e["top"],
                           "entry_zone": e["kind"], "bos_level": (l[brk] if short else h[brk]),
                           "bos_kind": "leg origin" if brk == origin else "5m MSS", "ifvg_tf": f.tf,
                           "entry_tf": "5m", "entry_mode": "touch", "entry_time": idx[q], "entry_price": entry,
                           "stop": stop, "target": tp, "target_level": ttag, "risk_pts": risk,
                           "planned_rr": abs(tp - entry) / risk, "exit": sim["exit"], "exit_time": idx[sim["exit_idx"]],
                           "exit_price": sim["exit_price"], "pnl_pts": pnl, "r_gross": pnl / risk,
                           "r_net": (pnl - B.COST[symbol]) / risk})
    finally:
        ifvg.LEG_MODE, ifvg.LEG_PIVOT, structure.DISP_MIN_CANDLES = saved
    out = pd.DataFrame(trades)
    if ONE_PER_ENTRY and len(out):
        # one trade per entry: several setups pointing at the same entry zone (same direction, zone and limit price) -> keep
        # only the first signal (earliest reversal candle; on a tie the earliest sweep)
        out = (out.sort_values(["reversal_time", "sweep_time"], kind="stable")
                  .drop_duplicates(["signal", "entry_zone", "fvg_bottom", "fvg_top", "entry_price"], keep="first")
                  .sort_values(["entry_time", "reversal_time"], kind="stable").reset_index(drop=True))
    return out
