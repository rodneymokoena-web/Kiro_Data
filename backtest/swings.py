"""Rule 1: Daily / Weekly / Monthly swing highs & lows, displayed on D, 4H, 1H, 15m, 5m.

Usage:
    .venv/bin/python swings.py

Definitions (edit the CONFIG block to change):
    * Swing high = bar whose High is the highest of PIVOT_LEFT bars before and PIVOT_RIGHT bars after.
      Swing low  = same with Lows. (TradingView ta.pivothigh / ta.pivotlow, Williams fractal for 2/2.)
    * A swing is only CONFIRMED when the PIVOT_RIGHT bars after it have closed -> no look-ahead.
      The level is drawn from the confirmation time, not from the pivot bar.
    * A level is "broken" when price later trades through it (High > swing high / Low < swing low).
      Broken lines stop at the break bar.
    * D/W/M candles are built from 1H data using the 17:00 New York rollover (CFD/FX broker standard),
      so every timeframe is aligned on the same clock. All timestamps are UTC.

Outputs:
    output/swings/{SYMBOL}_swing_levels.csv   every swing level with pivot/confirm/break times
    output/swings/{SYMBOL}_{tf}.png           chart per display timeframe
"""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------- CONFIG
PIVOT_LEFT = 2             # W / M swings: candles each side
PIVOT_RIGHT = 2
PIVOT_BY_TF = {}           # rule 1 (original): every timeframe uses PIVOT_LEFT / PIVOT_RIGHT; {"D": 1} = D 1 each side
D_EQUAL_ONLY = False       # rule 1 (original): every D swing counts; True = relative equal highs / lows only
EQ_TOL_ATR = 0.2           # "relatively equal" = within this x ATR(14) of the D candles
EQ_LOOKBACK = 60           # D candles back to look for the matching swing
import os as _os_b
SWEEP_TF = _os_b.environ.get("SWEEP_TF", "1H")   # timeframe on which the sweep (rejection) is judged: 5m/15m/1H/4H
BREAK_ON = _os_b.environ.get("BREAK_ON", "wick")   # "wick" = High/Low trades through; "close" = candle closes through;
                           # "sweep" = wick through AND close back (high: High>lvl & Close<lvl; low: Low<lvl & Close>lvl)
TEST_START = pd.Timestamp(os.environ.get("TEST_START", "2026-01-01"), tz="UTC")   # override: TEST_START=2024-01-01

# Data source for every script: "goat" = GoatFunded-Server MT5 M1 export (default), "pepperstone" = Pepperstone
# MT5 M1 export, "yahoo" = Yahoo Finance.
# Override per run with the environment variable, e.g.  DATA_SOURCE=yahoo .venv/bin/python backtest.py
DATA_SOURCE = os.environ.get("DATA_SOURCE", "goat").lower()
_SOURCES = {
    # name: (1h history file for D/W/M + 1h/4h display, 15m file, 5m file)
    "goat": (Path(__file__).parent / "data" / "goat", {
        "US100": ("US100_1h.csv", "US100_15m.csv", "US100_5m.csv"),
        "XAUUSD": ("XAUUSD_1h.csv", "XAUUSD_15m.csv", "XAUUSD_5m.csv"),
    }),
    "pepperstone": (Path(__file__).parent / "data" / "pepperstone", {
        "US100": ("US100_1h.csv", "US100_15m.csv", "US100_5m.csv"),
        "XAUUSD": ("XAUUSD_1h.csv", "XAUUSD_15m.csv", "XAUUSD_5m.csv"),
    }),
    "exness": (Path(__file__).parent / "data" / "exness", {                        # Exness USTEC / XAUUSD, built from ticks
        "US100": ("US100_1h.csv", "US100_15m.csv", "US100_5m.csv"),
        "XAUUSD": ("XAUUSD_1h.csv", "XAUUSD_15m.csv", "XAUUSD_5m.csv"),
        **{s: (f"{s}_1h.csv", f"{s}_15m.csv", f"{s}_5m.csv") for s in ("US500", "US30", "DE30", "UK100", "JP225")},
    }),
    "pepperstone_oos": (Path(__file__).parent / "data" / "pepperstone_oos", {      # Pepperstone 2021-2023 (out of sample)
        "US100": ("US100_1h.csv", "US100_15m.csv", "US100_5m.csv"),
        "XAUUSD": ("XAUUSD_1h.csv", "XAUUSD_15m.csv", "XAUUSD_5m.csv"),
    }),
    "goat_oos": (Path(__file__).parent / "data" / "goat_oos", {                    # GoatFunded 2021-2023 (out of sample)
        "US100": ("US100_1h.csv", "US100_15m.csv", "US100_5m.csv"),
        "XAUUSD": ("XAUUSD_1h.csv", "XAUUSD_15m.csv", "XAUUSD_5m.csv"),
    }),
    "yahoo": (Path(__file__).parent / "data", {
        "US100": ("US100_NQF_1h_ext.csv", "US100_NQF_15m.csv", "US100_NQF_5m.csv"),
        "XAUUSD": ("XAUUSD_GCF_1h_ext.csv", "XAUUSD_GCF_15m.csv", "XAUUSD_GCF_5m.csv"),
    }),
}
DATA, SYMBOLS = _SOURCES[DATA_SOURCE]
# Instruments traded by every script. Override per run, e.g.  TRADE_SYMBOLS=US100,XAUUSD .venv/bin/python swing.py
TRADE_SYMBOLS = os.environ.get("TRADE_SYMBOLS", "US100").split(",")
SYMBOLS = {k: v for k, v in SYMBOLS.items() if k in TRADE_SYMBOLS}
OUT = Path(__file__).parent / "output" / "swings"

# How much history each display chart shows (ending at the last bar)
DISPLAY_WINDOW = {"D": None, "4H": pd.Timedelta(days=120), "1H": pd.Timedelta(days=30),
                  "15m": pd.Timedelta(days=10), "5m": pd.Timedelta(days=3)}

STYLE = {  # swing timeframe -> colour, line width
    "M": ("#8e24aa", 2.4),
    "W": ("#1e88e5", 1.8),
    "D": ("#fb8c00", 1.1),
}
BAR_SIZE = {"1H": pd.Timedelta(hours=1), "15m": pd.Timedelta(minutes=15), "5m": pd.Timedelta(minutes=5)}


# ----------------------------------------------------------------------------- data
def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df[["Open", "High", "Low", "Close", "Volume"]].sort_index()


def trading_day(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Map UTC timestamps to the broker trading date (day rolls at 17:00 New York)."""
    return (idx.tz_convert("America/New_York") + pd.Timedelta(hours=7)).tz_localize(None).floor("D")


H4_GRID = os.environ.get("H4_GRID", "mt5")      # "mt5" (NY + 7h) | "tradingview" (NY + 6h = 18:00 NY session open)
H4_SHIFT = {"mt5": 7, "tradingview": 6}


def build_htf(h1: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Build D / W / M / 4H candles from 1H bars. Each row has Start/End (UTC) of the candle."""
    td = trading_day(h1.index)
    if tf == "D":
        key = td
    elif tf == "W":
        key = td.to_period("W-FRI").start_time
    elif tf == "M":
        key = td.to_period("M").start_time
    elif tf == "4H":
        # H4_GRID "tradingview": 4H candles start at the 18:00 New York session open (18, 22, 02, 06, 10, 14 NY), like
        #   TradingView's Pepperstone / GoatFunded US100 charts (and the Pine scripts). "mt5": MT5 server clock (NY + 7h).
        shifted = (h1.index.tz_convert("America/New_York") + pd.Timedelta(hours=H4_SHIFT[H4_GRID])).tz_localize(None)
        key = shifted.floor("4h")
    else:
        raise ValueError(tf)
    g = h1.assign(_k=key, _t=h1.index).groupby("_k")
    out = pd.DataFrame({
        "Open": g["Open"].first(), "High": g["High"].max(), "Low": g["Low"].min(),
        "Close": g["Close"].last(), "Volume": g["Volume"].sum(),
        "Start": g["_t"].min(), "End": g["_t"].max() + BAR_SIZE["1H"],
    })
    out.index = pd.DatetimeIndex(out["Start"])
    return out


# ----------------------------------------------------------------------------- swings
def _pivots(hi: np.ndarray, lo: np.ndarray, left: int, right: int) -> list[tuple[str, float, int]]:
    rows = []
    for i in range(left, len(hi) - right):
        lwin, rwin = slice(i - left, i), slice(i + 1, i + 1 + right)
        # strictly greater than left side, >= right side (first of equal highs wins, like TradingView)
        if hi[i] > hi[lwin].max() and hi[i] >= hi[rwin].max():
            rows.append(("high", hi[i], i))
        if lo[i] < lo[lwin].min() and lo[i] <= lo[rwin].min():
            rows.append(("low", lo[i], i))
    return rows


def _equal_levels(htf: pd.DataFrame, rows: list) -> list[tuple[str, float, int, int]]:
    """Relative equal highs / lows: a swing that sits within EQ_TOL_ATR x ATR(14) of an earlier swing of the
    same type (up to EQ_LOOKBACK candles back), with no candle in between trading beyond the pool.
    Level = highest of the equal highs (lowest of the equal lows); usable from the later swing's confirmation.
    Returns (type, level, index of the later swing, index of the first swing of the pool)."""
    hi, lo, c = htf["High"].to_numpy(), htf["Low"].to_numpy(), htf["Close"].to_numpy()
    pc = np.roll(c, 1); pc[0] = c[0]
    atr = pd.Series(np.maximum.reduce([hi - lo, np.abs(hi - pc), np.abs(lo - pc)])).rolling(14, min_periods=1).mean().to_numpy()
    out = []
    for kind in ("high", "low"):
        piv = [(p, i) for k, p, i in rows if k == kind]
        for a, (pj, j) in enumerate(piv):
            tol = EQ_TOL_ATR * atr[j]
            matched = []
            for pi, i in reversed(piv[:a]):
                if j - i > EQ_LOOKBACK:
                    break
                if abs(pi - pj) > tol:
                    continue
                pool = max(pi, pj) if kind == "high" else min(pi, pj)
                between = slice(i + 1, j)
                if j - i > 1:
                    if kind == "high" and hi[between].max() > pool:
                        continue
                    if kind == "low" and lo[between].min() < pool:
                        continue
                matched.append((pi, i))
            if matched:
                prices = [pj] + [m[0] for m in matched]
                level = max(prices) if kind == "high" else min(prices)
                if any(o[0] == kind and o[1] == level for o in out):
                    continue                    # 3rd+ equal high at the same pool price: same level
                out.append((kind, level, j, min(m[1] for m in matched)))
    return out


def find_swings(htf: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Return confirmed swing highs/lows. Level is usable from the close of bar i + right.
    Rule 1: D swings use PIVOT_BY_TF["D"] candles each side and, with D_EQUAL_ONLY, only relative equal
    highs/lows count as D liquidity. W / M use PIVOT_LEFT / PIVOT_RIGHT, every swing counts."""
    hi, lo = htf["High"].to_numpy(), htf["Low"].to_numpy()
    left = right = PIVOT_BY_TF.get(tf)
    if left is None:
        left, right = PIVOT_LEFT, PIVOT_RIGHT
    rows = _pivots(hi, lo, left, right)
    if tf == "D" and D_EQUAL_ONLY:
        rows = _equal_levels(htf, rows)
    else:
        rows = [(k, p, i, i) for k, p, i in rows]
    df = pd.DataFrame([{
        "tf": tf, "type": kind, "price": price,
        "pivot_time": htf["Start"].iloc[first],
        "confirmed_time": htf["End"].iloc[i + right],
    } for kind, price, i, first in rows], columns=["tf", "type", "price", "pivot_time", "confirmed_time"])
    return df


def fvg_far_edge_levels(h4: pd.DataFrame, label: str = "4HFVG") -> pd.DataFrame:
    """Rule 1 liquidity: every 4H FVG as a sweepable level at its FAR edge (the edge farthest from price, which
    sits on the side the FVG was left behind). Bearish FVG (price below it): its TOP is buy-side liquidity ("high").
    Bullish FVG (price above it): its BOTTOM is sell-side liquidity ("low"). Usable from the close of the FVG's 3rd candle.
    tf = "4HFVG"."""
    import ifvg
    f = ifvg.find_fvgs(h4.drop(columns=["Start", "End"]))
    import os
    mode = os.environ.get("FVG_LIQ_MODE", "fresh")   # all | intact (no 4H close through the far edge yet) | fresh (price never traded into the gap yet)
    H, L, C = (h4[k].to_numpy() for k in ("High", "Low", "Close"))
    rows = []
    for d, i, bot, top, inv in f[["dir", "idx", "bottom", "top", "inv_idx"]].itertuples(index=False):
        exp = pd.NaT
        if mode == "intact" and inv >= 0:
            exp = h4["Start"].iloc[inv] - pd.Timedelta(nanoseconds=1)
        elif mode == "fresh":
            later = np.arange(i + 1, len(h4))
            hit = later[(H[later] >= bot) if d == "bear" else (L[later] <= top)]
            if len(hit):
                exp = h4["End"].iloc[hit[0]] - pd.Timedelta(nanoseconds=1)
        rows.append({"tf": label, "type": "high" if d == "bear" else "low", "price": float(top if d == "bear" else bot),
                     "pivot_time": h4["Start"].iloc[i - 2], "confirmed_time": h4["End"].iloc[i], "expires": exp})
    return pd.DataFrame(rows, columns=["tf", "type", "price", "pivot_time", "confirmed_time", "expires"])


SIG_TOL = 0.0003   # price-match tolerance (fraction) for "significant 4H swing" qualifiers
SIG_4H_PIVOT = 2   # pivot size to detect 4H swings before testing them for significance


def significant_4h_levels(h1: pd.DataFrame) -> pd.DataFrame:
    """4H swing highs/lows that are SIGNIFICANT: a 4H swing (SIG_4H_PIVOT each side) kept only if, at the time it is
    confirmed, its price coincides with one of:
      1. a previous D / W / M swing high/low,
      2. a D / W / M FVG still unfilled (a PD array above 4H), the swing price inside the FVG zone,
      3. another unbroken 4H swing level at the same price (a 4H liquidity draw / equal high-low),
      4. a previous Asia/London/NY session high/low.
    tf = "4H" on the kept levels. Everything is causal (only data known by the swing's confirmation time)."""
    import ifvg
    htf = {t: build_htf(h1, t) for t in ("D", "W", "M", "4H")}
    h4 = htf["4H"]
    sw4 = find_swings(h4.assign(**{"_": 0}) if False else h4, "4H") if False else None
    # all 4H swings with SIG_4H_PIVOT each side
    saved = PIVOT_BY_TF.get("4H")
    PIVOT_BY_TF["4H"] = SIG_4H_PIVOT
    try:
        sw4 = find_swings(h4, "4H")
    finally:
        if saved is None:
            PIVOT_BY_TF.pop("4H", None)
        else:
            PIVOT_BY_TF["4H"] = saved
    # reference liquidity: D/W/M swings, D/W/M FVGs, session levels
    dwm = pd.concat([find_swings(htf[t], t) for t in ("D", "W", "M")], ignore_index=True)
    fvg = {t: ifvg.find_fvgs(htf[t].drop(columns=["Start", "End"])) for t in ("D", "W", "M")}
    for t in ("D", "W", "M"):
        fvg[t] = fvg[t].assign(done=htf[t]["End"].to_numpy()[fvg[t]["idx"].to_numpy()])
    sess = session_levels(h1, ("ASIA", "LONDON", "NY"), min_tf=("4H", "D", "W", "M"))  # significant session levels only

    kept = []
    for lv in sw4.itertuples(index=False):
        p, ct, kind = lv.price, lv.confirmed_time, lv.type
        tol = p * SIG_TOL
        ok = False
        # 1. previous D/W/M swing (same side), confirmed before this 4H swing
        d = dwm[(dwm["type"] == kind) & (dwm["confirmed_time"] <= ct)]
        if len(d) and (np.abs(d["price"].to_numpy() - p) <= tol).any():
            ok = True
        # 2. at the EDGE of an unfilled D/W/M FVG (a PD array above 4H): swing price within tol of the FVG top or bottom
        if not ok:
            for t in ("D", "W", "M"):
                f = fvg[t]
                f = f[f["done"] <= ct]
                if len(f) and ((np.abs(f["top"].to_numpy() - p) <= tol) | (np.abs(f["bottom"].to_numpy() - p) <= tol)).any():
                    ok = True
                    break
        # 3. another 4H swing (same side) at the same price, confirmed earlier (4H liquidity draw / equal level)
        if not ok:
            o4 = sw4[(sw4["type"] == kind) & (sw4["confirmed_time"] < ct)]
            if len(o4) and (np.abs(o4["price"].to_numpy() - p) <= tol).any():
                ok = True
        # 4. previous session high/low (same side), confirmed before this 4H swing
        if not ok and len(sess):
            se = sess[(sess["type"] == kind) & (sess["confirmed_time"] <= ct)]
            if len(se) and (np.abs(se["price"].to_numpy() - p) <= tol).any():
                ok = True
        if ok:
            kept.append({"tf": "4H", "type": kind, "price": p, "pivot_time": lv.pivot_time, "confirmed_time": ct})
    return pd.DataFrame(kept, columns=["tf", "type", "price", "pivot_time", "confirmed_time"])


# ICT sessions on the New York clock (hour ranges, NY time). A session level is the high/low of a completed session.
SESSIONS = {"ASIA": (20, 24), "LONDON": (2, 5), "NY": (7, 10)}


SESSION_MIN_TF = ("1H",)   # a session high/low counts only if it is also a swing on one of these TFs ("1H","4H","D"...)
SESSION_SWING_TOL = 0.0001  # price match tolerance (fraction) between the session extreme and the swing


def _swing_prices(h1: pd.DataFrame, tfs) -> dict:
    """{tf: (array of swing-high prices, array of swing-low prices)} for the requested timeframes (1H = the 1H bars)."""
    out = {}
    for tf in tfs:
        bars = h1.assign(Start=h1.index, End=h1.index + BAR_SIZE["1H"]) if tf == "1H" else build_htf(h1, tf)
        sw = find_swings(bars, tf)
        out[tf] = (sw.loc[sw["type"] == "high", "price"].to_numpy(), sw.loc[sw["type"] == "low", "price"].to_numpy())
    return out


SESSION_VALID = pd.Timedelta(days=7)   # a session high/low stays sweepable for this long after the session closes


def session_levels(h1: pd.DataFrame, which=("ASIA", "LONDON", "NY"), min_tf=None) -> pd.DataFrame:
    """High and low of each completed session as liquidity levels (tf = session name), confirmed at the session close.
    Each level carries an `expires` time = confirmed_time + SESSION_VALID; after that it is no longer sweepable.
    min_tf (default SESSION_MIN_TF): keep a session extreme only if it also lines up with a swing high/low on one of
    those timeframes (1H and above). min_tf=() keeps every session extreme."""
    if min_tf is None:
        min_tf = SESSION_MIN_TF
    swings = _swing_prices(h1, min_tf) if min_tf else None
    ny = h1.index.tz_convert("America/New_York")
    hour = ny.hour + ny.minute / 60.0
    day = (ny + pd.Timedelta(hours=7)).tz_localize(None).floor("D")       # trading-day key (rolls 17:00 NY)

    def is_swing(price: float, kind: str) -> bool:
        if swings is None:
            return True
        tol = price * SESSION_SWING_TOL
        for hi_p, lo_p in swings.values():
            arr = hi_p if kind == "high" else lo_p
            if len(arr) and np.min(np.abs(arr - price)) <= tol:
                return True
        return False

    rows = []
    for name in which:
        lo_h, hi_h = SESSIONS[name]
        inb = (hour >= lo_h) & (hour < hi_h)
        if not inb.any():
            continue
        sub = h1[inb].assign(_d=day[inb])
        g = sub.groupby("_d")
        hi = g["High"].max(); lo = g["Low"].min()
        end = g.apply(lambda x: x.index.max() + BAR_SIZE["1H"], include_groups=False)
        for d in hi.index:
            if is_swing(float(hi[d]), "high"):
                rows.append({"tf": name, "type": "high", "price": float(hi[d]), "pivot_time": end[d],
                             "confirmed_time": end[d], "expires": end[d] + SESSION_VALID})
            if is_swing(float(lo[d]), "low"):
                rows.append({"tf": name, "type": "low", "price": float(lo[d]), "pivot_time": end[d],
                             "confirmed_time": end[d], "expires": end[d] + SESSION_VALID})
    return pd.DataFrame(rows, columns=["tf", "type", "price", "pivot_time", "confirmed_time", "expires"])


def _sweep_frame(h1: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Bars for the sweep timeframe. 4H via build_htf; 5m/15m loaded from the current data source; else h1."""
    if tf == "4H":
        return build_htf(h1, "4H").drop(columns=["Start", "End"])
    if tf in ("5m", "15m"):
        import os
        f = DATA / SYMBOLS[list(SYMBOLS)[0]][2 if tf == "5m" else 1]
        return load(f)
    return h1



def add_break_times(levels: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """First bar (after confirmation) that sweeps each level, per BREAK_ON:
    "wick"  = High/Low trades through;  "close" = candle closes through;
    "sweep" = wick through AND close back the other way (high: High>level & Close<level; low: Low<level & Close>level)."""
    hi_col, lo_col = ("High", "Low") if BREAK_ON == "wick" else ("Close", "Close")
    breaks = []
    for _, lv in levels.iterrows():
        after = bars[bars.index >= lv["confirmed_time"]]
        exp = lv.get("expires", pd.NaT) if hasattr(lv, "get") else pd.NaT
        if pd.notna(exp):                                    # session levels: only sweepable until they expire
            after = after[after.index <= exp]
        if BREAK_ON == "sweep":
            if lv["type"] == "high":
                hit = after[(after["High"] > lv["price"]) & (after["Close"] < lv["price"])]
            else:
                hit = after[(after["Low"] < lv["price"]) & (after["Close"] > lv["price"])]
        else:
            hit = after[after[hi_col] > lv["price"]] if lv["type"] == "high" else after[after[lo_col] < lv["price"]]
        breaks.append(hit.index[0] if len(hit) else pd.NaT)
    return levels.assign(broken_time=breaks)



SWEEP5M_MODE = _os_b.environ.get("SWEEP5M_MODE", "ab12")   # "a" = 5m wick + close back | "ab" = also a 5m close beyond the level followed by two displacement candles
SWEEP5M_DISP_ATR = float(_os_b.environ.get("SWEEP5M_DISP_ATR", "1.0"))   # the two displacement candles must move >= this x ATR14 (5m)


def add_break_times_5m(levels: pd.DataFrame, m5: pd.DataFrame, h4_index: pd.DatetimeIndex | None) -> pd.DataFrame:
    """Intraday sweep judged on 5m candles; broken_time = the 4H candle (open time) that contains the confirmation.
    (A) a 5m candle wicks through the level and CLOSES back (high level: high > level, close < level);
    (B) a 5m candle CLOSES beyond the level and the next two 5m candles are strong displacement candles (consecutive, same
        direction as the reversal, moving >= SWEEP5M_DISP_ATR x ATR14 from the first one's open to the second one's close),
        the SECOND one closing beyond the low (high level) / high (low level) of the sweeping candle - of the FIRST
        sweeping candle when two candles closed beyond the level (ab12: 1 or 2 candles, not 3+).
    Confirmed at the close of the last candle of (A) or (B). Session levels only count until they expire."""
    o, h, l, c = (m5[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    n = len(c)
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().to_numpy()
    bear, bull = c < o, c > o
    # dS[k]: candles k+1, k+2 are two strong bearish displacement candles (together >= SWEEP5M_DISP_ATR x ATR14);
    # c2[k] = close of the second one (compared below with the low of the first sweeping candle)
    dS = np.zeros(n, dtype=bool); dL = np.zeros(n, dtype=bool); c2 = np.full(n, np.nan)
    if n > 2:
        dS[:-2] = bear[1:-1] & bear[2:] & ((o[1:-1] - c[2:]) >= SWEEP5M_DISP_ATR * atr[2:])
        dL[:-2] = bull[1:-1] & bull[2:] & ((c[2:] - o[1:-1]) >= SWEEP5M_DISP_ATR * atr[2:])
        c2[:-2] = c[2:]
    idx5 = pd.DatetimeIndex(m5.index).as_unit("ns")
    h4_index = pd.DatetimeIndex(h4_index).as_unit("ns") if h4_index is not None else None
    out = []
    for lv in levels.itertuples(index=False):
        a0 = int(idx5.searchsorted(pd.Timestamp(lv.confirmed_time).as_unit("ns"), side="left"))
        exp = getattr(lv, "expires", pd.NaT)
        a1 = int(idx5.searchsorted(pd.Timestamp(exp).as_unit("ns"), side="right")) if pd.notna(exp) else n
        if a0 >= a1:
            out.append(pd.NaT); continue
        hi_l = lv.type == "high"
        H_, L_, C_ = h[a0:a1], l[a0:a1], c[a0:a1]
        thr = (C_ > lv.price) if hi_l else (C_ < lv.price)                  # closed beyond the level
        p1 = np.r_[False, thr[:-1]]                                          # the candle before also closed beyond
        if SWEEP5M_MODE == "ab12":                                           # the sweep is 1 or 2 candles closing beyond the level (not 3+)
            p2 = np.r_[False, False, thr[:-2]]
            thr = thr & ~(p1 & p2)
        else:
            p1 = np.zeros_like(thr)
        # reference candle: the sweeping candle (1-candle sweep) or the FIRST of the two sweeping candles (2-candle sweep)
        L1, H1_ = np.r_[np.nan, L_[:-1]], np.r_[np.nan, H_[:-1]]
        refL, refH = np.where(p1, L1, L_), np.where(p1, H1_, H_)
        C2 = c2[a0:a1]
        if hi_l:
            A = (H_ > lv.price) & (C_ < lv.price)
            B = thr & dS[a0:a1] & (C2 < refL) if SWEEP5M_MODE in ("ab", "ab12") else None
        else:
            A = (L_ < lv.price) & (C_ > lv.price)
            B = thr & dL[a0:a1] & (C2 > refH) if SWEEP5M_MODE in ("ab", "ab12") else None
        best = None
        if A.any():
            best = int(np.argmax(A))
        if B is not None and B.any():
            kb = int(np.argmax(B)) + 2
            best = kb if best is None else min(best, kb)
        if best is None:
            out.append(pd.NaT); continue
        t = idx5[a0 + best]
        if h4_index is None:                       # pin to the 5m candle that confirms the sweep
            out.append(t); continue
        pos = int(h4_index.searchsorted(t, side="right")) - 1
        out.append(h4_index[pos] if pos >= 0 else pd.NaT)
    return levels.assign(broken_time=out)


def refine_breaks(levels: pd.DataFrame, fine: pd.DataFrame) -> pd.DataFrame:
    """Re-time breaks on finer data, but only where the fine data actually covers the break.
    Levels broken before the fine data starts keep their 1H break time."""
    lv = levels.copy()
    need = lv["broken_time"].isna() | (lv["broken_time"] >= fine.index[0])
    if need.any():
        lv.loc[need, "broken_time"] = add_break_times(lv[need].drop(columns="broken_time"), fine)["broken_time"]
    return lv


# ----------------------------------------------------------------------------- plotting
def draw_candles(ax, df: pd.DataFrame) -> None:
    x = np.arange(len(df))
    up = df["Close"] >= df["Open"]
    col = np.where(up, "#26a69a", "#ef5350")
    ax.vlines(x, df["Low"], df["High"], color=col, linewidth=0.6)
    body_lo = np.minimum(df["Open"], df["Close"])
    body_h = np.maximum((df["Close"] - df["Open"]).abs(), (df["High"] - df["Low"]).max() * 0.0005)
    ax.bar(x, body_h, bottom=body_lo, color=col, width=0.7, linewidth=0)


def plot(symbol: str, disp_tf: str, bars: pd.DataFrame, levels: pd.DataFrame, path: Path) -> int:
    window = DISPLAY_WINDOW[disp_tf]
    end = bars.index[-1]
    start = max(TEST_START, end - window) if window is not None else TEST_START
    df = bars[bars.index >= start]
    if df.empty:
        return 0
    t0, t1 = df.index[0], df.index[-1]
    pad = (df["High"].max() - df["Low"].min()) * 0.15
    ymin, ymax = df["Low"].min() - pad, df["High"].max() + pad

    fig, ax = plt.subplots(figsize=(18, 8))
    draw_candles(ax, df)
    pos = pd.Series(np.arange(len(df)), index=df.index)

    def xpos(ts):  # timestamp -> candle index on this chart
        return int(pos.index.searchsorted(ts, side="left"))

    drawn, labels = 0, []
    for _, lv in levels.sort_values("tf").iterrows():
        c_time, b_time = lv["confirmed_time"], lv["broken_time"]
        if c_time > t1 or (pd.notna(b_time) and b_time < t0):
            continue  # not active in this window
        if not (ymin <= lv["price"] <= ymax):
            continue
        x0 = max(xpos(c_time), 0)
        broken = pd.notna(b_time) and b_time <= t1
        x1 = xpos(b_time) if broken else len(df) - 1
        colour, lw = STYLE[lv["tf"]]
        ls = "-" if lv["type"] == "high" else "--"
        ax.hlines(lv["price"], x0, x1, color=colour, linewidth=lw, linestyle=ls, alpha=0.35 if broken else 0.95)
        if broken:
            ax.plot(x1, lv["price"], marker="x", color=colour, markersize=6)
        else:
            labels.append((lv["type"], round(lv["price"], 2), lv["tf"]))
        drawn += 1

    # One label per price: same level on several timeframes -> "M/W/D L 27201.5" in the highest-TF colour
    order = {"M": 0, "W": 1, "D": 2}
    merged: dict[tuple, set] = {}
    for kind, price, tf in labels:
        merged.setdefault((kind, price), set()).add(tf)
    placed: list[float] = []
    min_gap = (ymax - ymin) * 0.018
    for (kind, price), tfs in sorted(merged.items(), key=lambda kv: kv[0][1]):
        tfs = sorted(tfs, key=order.get)
        y = price
        while any(abs(y - p) < min_gap for p in placed):  # nudge labels that would still collide
            y += min_gap
        placed.append(y)
        ax.text(len(df) + 0.5, y, f'{"/".join(tfs)} {"H" if kind == "high" else "L"} {price:.1f}',
                color=STYLE[tfs[0]][0], fontsize=8, va="center", fontweight="bold")

    # x-axis: label with dates
    step = max(len(df) // 12, 1)
    ticks = list(range(0, len(df), step))
    fmt = "%Y-%m-%d" if disp_tf in ("D", "4H") else "%m-%d %H:%M"
    ax.set_xticks(ticks)
    ax.set_xticklabels([df.index[i].strftime(fmt) for i in ticks], rotation=30, ha="right", fontsize=8)
    ax.set_xlim(-1, len(df) + len(df) * 0.06)
    ax.set_ylim(ymin, ymax)
    ax.grid(alpha=0.15)
    ax.set_title(f"{symbol}  {disp_tf}  |  {t0:%Y-%m-%d %H:%M} -> {t1:%Y-%m-%d %H:%M} UTC  |  "
                 f"swings: pivot {PIVOT_LEFT}/{PIVOT_RIGHT}, break on {BREAK_ON}", fontsize=11)
    legend = [plt.Line2D([], [], color=STYLE[k][0], lw=STYLE[k][1], label=n)
              for k, n in (("M", "Monthly"), ("W", "Weekly"), ("D", "Daily"))]
    legend += [plt.Line2D([], [], color="gray", ls="-", label="Swing high"),
               plt.Line2D([], [], color="gray", ls="--", label="Swing low"),
               plt.Line2D([], [], color="gray", marker="x", ls="", label="Broken")]
    ax.legend(handles=legend, loc="upper left", fontsize=8, ncol=6)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return drawn


# ----------------------------------------------------------------------------- main
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for symbol, (h1_file, m15_file, m5_file) in SYMBOLS.items():
        h1 = load(DATA / h1_file)
        htf = {tf: build_htf(h1, tf) for tf in ("D", "W", "M", "4H")}
        levels = pd.concat([find_swings(htf[tf], tf) for tf in ("M", "W", "D")], ignore_index=True)
        levels = add_break_times(levels, h1)
        levels.sort_values(["confirmed_time", "tf"]).to_csv(OUT / f"{symbol}_swing_levels.csv", index=False)

        display = {"D": htf["D"], "4H": htf["4H"], "1H": h1,
                   "15m": load(DATA / m15_file), "5m": load(DATA / m5_file)}
        print(f"\n{symbol}: {len(levels)} swing levels "
              f"(M={sum(levels.tf == 'M')}, W={sum(levels.tf == 'W')}, D={sum(levels.tf == 'D')})")
        active = levels[(levels.confirmed_time <= h1.index[-1]) & levels.broken_time.isna()]
        for tf in ("M", "W", "D"):
            a = active[active.tf == tf]
            hs = ", ".join(f"{p:.1f}" for p in a[a.type == "high"].price.sort_values())
            ls = ", ".join(f"{p:.1f}" for p in a[a.type == "low"].price.sort_values())
            print(f"  unbroken {tf}: highs [{hs or '-'}]  lows [{ls or '-'}]")
        for disp_tf, bars in display.items():
            lv = levels if disp_tf in ("D", "4H", "1H") else refine_breaks(levels, bars)
            n = plot(symbol, disp_tf, bars, lv, OUT / f"{symbol}_{disp_tf}.png")
            print(f"  chart {disp_tf:>3}: {n} levels drawn -> output/swings/{symbol}_{disp_tf}.png")


if __name__ == "__main__":
    main()
