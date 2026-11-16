"""Extra stop levels (before the buffer). SHORT described; LONG is the mirror image.

    "1H IFVG"          above the top of the 1H IFVG (the rule 5 1H FVG formed on the retest into the 4H IFVG).
    "1H FVG above 4H"  above the top of the HIGHEST 1H FVG of the rule 5 retest leg (origin -> 1H signal) whose bottom
                       is at or above the 4H IFVG bottom; none -> the 1H IFVG.
    "4H OB leg"        first order block of the 4H sweeping leg: the last UP-close 4H candle at or before the 4H candle
                       of the sweep extreme; stop above its high.
    "4H OB disp"       the last UP-close 4H candle before the 4H displacement run that inverted the 4H FVG (may be after
                       the extreme); stop above its high. M6 setups (no 4H displacement): same as "4H OB leg".
    "1H OB bull"       first 1H order block of the 4H sweeping leg ABOVE the entry: bullish OB = a down-close 1H
                       candle followed within OB_BREAK 1H candles by a close above its high; the one with the lowest
                       high above the entry; stop above its high. None -> the sweep extreme ("ob_fallback").
    "1H OB bear"       same with bearish OB = an up-close 1H candle followed within OB_BREAK candles by a close below
                       its low.
    Sweeping leg on 1H: from the lowest 1H low after the start of the last 4H swing low before the sweep (rule 2 leg)
    up to the 1H sweep extreme (rule 5 anchor).
Intraday only (5m), level_ltf():
    "5m OB leg bull/bear"     the 5m order block (same OB definitions) of the 4H sweeping leg nearest ABOVE the entry.
    "5m OB retest bull/bear"  the 5m order block of the intraday retest leg (1H IFVG retest -> entry, the move that
                              makes the 5m MSS) nearest above the entry.
    None -> np.nan (backtest falls back to the previous 1H candle; last_fallback = True).
Returns np.nan when there is no such level.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import structure

KINDS = ("1H IFVG", "1H FVG above 4H", "4H OB leg", "4H OB disp", "1H OB bull", "1H OB bear")
LTF_KINDS = ("5m OB leg bull", "5m OB leg bear", "5m OB retest bull", "5m OB retest bear")
OB_BREAK = 3          # 1H candles after the OB candle in which a close must break it
LEG_PIVOT = 2         # 4H swing size for the start of the sweeping leg
last_fallback = False # set by level(): True when a 1H OB stop fell back to the sweep extreme
OB_LOOKBACK = 30      # 4H candles searched back for the order block


def _ob(h4: pd.DataFrame, start: int, short: bool) -> float:
    o, h, l, c = (h4[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    for i in range(start, max(-1, start - OB_LOOKBACK), -1):
        if (short and c[i] > o[i]) or (not short and c[i] < o[i]):
            return float(h[i] if short else l[i])
    return np.nan


def _leg_start_1h(st: dict, r5: dict, h1: pd.DataFrame, h4: pd.DataFrame) -> int:
    """1H index of the start of the 4H sweeping leg (lowest low after the last 4H swing low before the sweep)."""
    short = st["signal"] == "short"
    l4, h4h = h4["Low"].to_numpy(), h4["High"].to_numpy()
    s4 = int(h4.index.searchsorted(st["sweep_time"], side="right") - 1)
    p, org = LEG_PIVOT, max(0, s4 - 60)
    for i in range(s4 - p, p - 1, -1):
        if (short and l4[i] == l4[i - p:i + p + 1].min()) or (not short and h4h[i] == h4h[i - p:i + p + 1].max()):
            org = i
            break
    a = int(h1.index.searchsorted(h4.index[org]))
    b = int(r5["x"]["anchor"])
    if b <= a:
        return b
    seg = h1["Low"].to_numpy()[a:b + 1] if short else h1["High"].to_numpy()[a:b + 1]
    return a + int(np.argmin(seg) if short else np.argmax(seg))


def _ob_window(bars: pd.DataFrame, a: int, b: int, bull: bool, short: bool, entry: float) -> float:
    """Order block in bars[a..b] nearest beyond the entry (above for a short). bull = bullish OB (short: down candle
    followed within OB_BREAK candles by a close above its high), else bearish OB (up candle then a close below its low)."""
    o, h, l, c = (bars[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    best = np.nan
    for i in range(max(a, 0), b + 1):
        up, dn = c[i] > o[i], c[i] < o[i]
        nxt = c[i + 1:min(i + 1 + OB_BREAK, b + 1)]
        if bull:
            ok = (dn and (nxt > h[i]).any()) if short else (up and (nxt < l[i]).any())
        else:
            ok = (up and (nxt < l[i]).any()) if short else (dn and (nxt > h[i]).any())
        if not ok:
            continue
        lv = h[i] if short else l[i]
        if (short and lv > entry and (np.isnan(best) or lv < best)) or \
           (not short and lv < entry and (np.isnan(best) or lv > best)):
            best = lv
    return best


def level_ltf(kind: str, st: dict, r5: dict, h1: pd.DataFrame, h4: pd.DataFrame, ltf: pd.DataFrame, e: dict,
              entry: float) -> float:
    global last_fallback
    short = st["signal"] == "short"
    bull = kind.endswith("bull")
    if " leg " in kind:
        a1, b1 = _leg_start_1h(st, r5, h1, h4), int(r5["x"]["anchor"])
        a = int(ltf.index.searchsorted(h1.index[a1]))
        b = int(ltf.index.searchsorted(h1.index[b1] + pd.Timedelta(hours=1))) - 1
    else:
        a, b = int(e["x"]["retest"]), int(e["x"]["entry"]) - 1
    lv = _ob_window(ltf, a, b, bull, short, entry) if b >= a else np.nan
    last_fallback = bool(np.isnan(lv))
    return lv


def _ob_1h(kind: str, st: dict, r5: dict, h1: pd.DataFrame, h4: pd.DataFrame, entry: float) -> float:
    global last_fallback
    short = st["signal"] == "short"
    o, h, l, c = (h1[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    a, b = _leg_start_1h(st, r5, h1, h4), int(r5["x"]["anchor"])
    best = np.nan
    for i in range(a, b + 1):
        up, dn = c[i] > o[i], c[i] < o[i]
        nxt = c[i + 1:min(i + 1 + OB_BREAK, b + 1)]
        if kind == "1H OB bull":            # short: bullish OB (down candle, then a close above its high)
            ok = (dn and (nxt > h[i]).any()) if short else (up and (nxt < l[i]).any())
        else:                               # short: bearish OB (up candle, then a close below its low)
            ok = (up and (nxt < l[i]).any()) if short else (dn and (nxt > h[i]).any())
        if not ok:
            continue
        lv = h[i] if short else l[i]
        if (short and lv > entry and (np.isnan(best) or lv < best)) or \
           (not short and lv < entry and (np.isnan(best) or lv > best)):
            best = lv
    last_fallback = np.isnan(best)
    return float(r5["x"]["extreme"]) if np.isnan(best) else float(best)


def level(kind: str, st: dict, r5: dict, h1_fvgs: pd.DataFrame, h4: pd.DataFrame, h1: pd.DataFrame | None = None,
          entry: float | None = None) -> float:
    short = st["signal"] == "short"
    if kind in ("1H OB bull", "1H OB bear"):
        return _ob_1h(kind, st, r5, h1, h4, entry)
    if kind == "1H IFVG":
        return float(r5["h1_fvg_top"] if short else r5["h1_fvg_bottom"])
    if kind == "1H FVG above 4H":
        x = r5["x"]
        f = h1_fvgs[(h1_fvgs["dir"] == ("bull" if short else "bear")) & (h1_fvgs["idx"] - 2 >= x["origin"])
                    & (h1_fvgs["idx"] <= x["inv_idx"])]
        f = f[f["bottom"] >= st["fvg_bottom"]] if short else f[f["top"] <= st["fvg_top"]]
        if f.empty:
            return float(r5["h1_fvg_top"] if short else r5["h1_fvg_bottom"])
        return float(f["top"].max() if short else f["bottom"].min())
    e4 = int(h4.index.searchsorted(st["extreme_time"], side="right") - 1)
    # only 4H candles already completed at the signal (M6 signals come on 1H, inside a forming 4H candle)
    done = int(h4.index.searchsorted(st["signal_time"] - pd.Timedelta(hours=4), side="right") - 1)
    e4 = min(e4, done)
    if kind == "4H OB leg" or "extreme_span" in st:          # extreme_span = M6 setup (no 4H displacement run)
        return _ob(h4, e4, short)
    if kind == "4H OB disp":
        j = int(st["x_inv_idx"])
        ok, run_len, _, run_start = structure.displacement(h4, j, short)
        return _ob(h4, run_start - 1 if run_len else j, short)
    raise ValueError(kind)
