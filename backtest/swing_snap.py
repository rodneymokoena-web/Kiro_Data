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

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

import ifvg
import stops_ext
import swing as W
from backtest import COST, SL_BUFFER
from ifvg_1h import RETEST_WINDOW
from ote import BEAR, BULL, H4, _axis
from swings import DATA, SYMBOLS, add_break_times, build_htf, draw_candles, find_swings, load

PLOT = False                 # set True (or SN.PLOT=True) to save a chart per trade in output/swing_snap/trades/
OUT = __import__("pathlib").Path(__file__).parent / "output" / "swing_snap"

LOST: dict[str, int] = {}   # why setups did not become trades (reset by the caller)
STOP_KIND = "1H OB of drop FVG"   # "4H IFVG" = beyond the 4H IFVG far edge; "1H OB of drop FVG" (snapshot rules)
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
# Rule 1 liquidity for the swing model: 4H / D / W / M (4H swings with RULE1_4H_PIVOT candles each side). Set
# LIQ_TFS_RULE1 = ("M", "W", "D") for D/W/M only.
LIQ_TFS_RULE1 = ("M", "W", "D", "4H")
RULE1_4H_PIVOT = 10
# TARGET "liquidity": the OPPOSITE liquidity draw = nearest unbroken swing low (short) / high (long) beyond the entry
# on LIQ_TFS ("4H" swings with LIQ_4H_PIVOT candles each side, "D", "W", "M"), confirmed and not yet traded through at
# the fill. LIQ_MIN_RR > 0: skip levels closer than LIQ_MIN_RR x risk and take the next one.
LIQ_TFS = ("4H",)
LIQ_4H_PIVOT = 2
LIQ_MIN_RR = 0.0
LEG_LOOKBACK_4H = 60    # the 4H FVG may be at most this many 4H candles before the sweep
REQUIRE_MSS = "mss"     # "mss" (1H MSS required) | "none"
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
    import swings
    keys = ("INVERT_ON", "WICK_CLOSE", "CISD_MODE", "REQUIRE", "WAIT_1H", "MSS_MODE")
    saved = {k: getattr(V3, k) for k in keys}
    saved2 = (ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK, structure.DISP_MIN_CANDLES, ifvg.SWEEP_TFS, dict(swings.PIVOT_BY_TF))
    for k, v in zip(keys, ("close", "any", "1h_close", REQUIRE_MSS, 0, "ext")):
        setattr(V3, k, v)
    ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK, structure.DISP_MIN_CANDLES = "any", LEG_LOOKBACK_4H, disp_min
    ifvg.SWEEP_TFS = LIQ_TFS_RULE1                                    # rule 1 liquidity for the swing model
    if "4H" in LIQ_TFS_RULE1:
        swings.PIVOT_BY_TF = {**swings.PIVOT_BY_TF, "4H": RULE1_4H_PIVOT}
    try:
        return V3.build_setups(h1)
    finally:
        for k, v in saved.items():
            setattr(V3, k, v)
        ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK, structure.DISP_MIN_CANDLES, ifvg.SWEEP_TFS, swings.PIVOT_BY_TF = saved2


FVG_PICK = "nearest"    # "nearest" (closest to the 4H IFVG) | "farthest" (most extreme of the leg)
FVG_OVERLAP = "outside"  # "outside" = FVG fully beyond the 4H IFVG | "overlap" = its far edge beyond the IFVG edge


def _fvg_beyond_ifvg(st: dict, h1_fvgs: pd.DataFrame, anchor: int, q: int, pick: str, overlap: str) -> tuple[float, str]:
    """Short: a bullish 1H FVG of the sweeping leg sitting ABOVE the 4H IFVG; stop above its top. The leg = sweep ->
    1H sweep extreme (anchor). 'outside' = FVG bottom >= 4H IFVG top; 'overlap' = FVG top > 4H IFVG top."""
    short = st["signal"] == "short"
    s1 = int(st["x_sweep_idx"]) if "x_sweep_idx" in st else anchor
    edge4 = st["fvg_top"] if short else st["fvg_bottom"]                 # far edge of the 4H IFVG
    f = h1_fvgs[(h1_fvgs["dir"] == ("bull" if short else "bear")) & (h1_fvgs["idx"] - 2 >= s1 - 60)
                & (h1_fvgs["idx"] <= anchor)]
    f = (f[f["bottom"] >= edge4] if short else f[f["top"] <= edge4]) if overlap == "outside" \
        else (f[f["top"] > edge4] if short else f[f["bottom"] < edge4])
    if f.empty:
        return np.nan, ""
    if pick == "nearest":
        row = f.loc[f["top"].idxmin()] if short else f.loc[f["bottom"].idxmax()]
    else:
        row = f.loc[f["top"].idxmax()] if short else f.loc[f["bottom"].idxmin()]
    return float(row["top"] if short else row["bottom"]), "1H FVG beyond 4H IFVG"


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


def liquidity_levels(h1: pd.DataFrame, levels: pd.DataFrame, tfs, pivot4: int) -> pd.DataFrame:
    """Swing levels (with break times) on the requested timeframes."""
    import swings
    parts = [levels[levels["tf"].isin([t for t in tfs if t != "4H"])]]
    if "4H" in tfs:
        saved = dict(swings.PIVOT_BY_TF)
        swings.PIVOT_BY_TF = {**saved, "4H": pivot4}
        try:
            parts.append(add_break_times(find_swings(build_htf(h1, "4H"), "4H"), h1))
        finally:
            swings.PIVOT_BY_TF = saved
    return pd.concat(parts, ignore_index=True)


def liquidity_target(liq: pd.DataFrame, short: bool, entry: float, risk: float, t: pd.Timestamp, min_rr: float):
    lv = liq[(liq["confirmed_time"] <= t) & (liq["broken_time"].isna() | (liq["broken_time"] > t))]
    if short:
        lv = lv[(lv["type"] == "low") & (lv["price"] < entry - min_rr * risk)]
    else:
        lv = lv[(lv["type"] == "high") & (lv["price"] > entry + min_rr * risk)]
    if lv.empty:
        return np.nan, ""
    row = lv.loc[lv["price"].idxmax() if short else lv["price"].idxmin()]
    return float(row["price"]), f"{row['tf']}{'L' if short else 'H'} {row['price']:.2f}"


def plot_trade(symbol: str, tr: dict, st: dict, h1: pd.DataFrame, levels: pd.DataFrame, q: int, k: int,
               path) -> None:
    """Chart with Rule 1 liquidity levels, the Rule 2 swept level + sweep candle, the 4H IFVG, entry / stop / target."""
    short = tr["signal"] == "short"
    idx = h1.index
    s1 = int(idx.searchsorted(st["sweep_time"]))
    anc = int(idx.searchsorted(st["extreme_time"]))
    # window: a bit before the sweep to a bit after the exit (trade entry q is the anchor, not raw setup indices)
    a = max(0, min(s1, q) - 24)
    b = min(len(h1), k + 16)
    df = h1.iloc[a:b]
    fig, ax = plt.subplots(figsize=(16, 7))
    draw_candles(ax, df)
    xmax = len(df) - 1

    # Rule 1: D/W/M liquidity levels that are near the trade's price range and still relevant in the window.
    # Show levels unbroken as of the window end (plus those broken inside the window), within the price range shown.
    col = {"M": "#8e24aa", "W": "#1e88e5", "D": "#fb8c00"}
    lo, hi = df["Low"].min(), df["High"].max()
    pad = (hi - lo) * 0.25
    t_end = idx[min(b - 1, len(h1) - 1)]
    vis = levels[(levels["confirmed_time"] <= t_end) & (levels["price"] >= lo - pad) & (levels["price"] <= hi + pad)
                 & (levels["broken_time"].isna() | (levels["broken_time"] >= idx[a]))]
    for lv in vis.itertuples(index=False):
        bt = lv.broken_time
        x_end = (idx.searchsorted(bt) - a) if (pd.notna(bt) and idx.searchsorted(bt) < b) else xmax + 3
        x_start = max(0, idx.searchsorted(lv.confirmed_time) - a)
        ax.hlines(lv.price, x_start, x_end, color=col[lv.tf], lw=1.0 if lv.tf == "D" else 1.8,
                  alpha=0.95 if lv.tf == "M" else (0.75 if lv.tf == "W" else 0.45))
        ax.text(x_end + 0.3, lv.price, lv.tf, fontsize=7, color=col[lv.tf], va="center")

    # Rule 2: the swept level(s) (bold) and the sweep candle. tr["swept"] = e.g. "DH 25072.40, WH 25378.00"
    sc = "#d32f2f" if short else "#2e7d32"
    import re
    swept_prices = [float(x) for x in re.findall(r"\d+\.?\d*", str(tr.get("swept", "")))]
    for sp in swept_prices:
        ax.hlines(sp, 0, xmax + 3, color=sc, lw=2.2)
    if swept_prices:
        sp = max(swept_prices) if short else min(swept_prices)
        ax.text(0.2, sp, f" Rule 2 swept: {tr['swept']}", fontsize=8, color=sc,
                va="bottom" if short else "top", fontweight="bold")
    if a <= s1 < b:
        ax.axvline(s1 - a, color=sc, ls=":", lw=1, alpha=0.6)
        y = h1["High"].iat[s1] if short else h1["Low"].iat[s1]
        ax.annotate("sweep", (s1 - a, y), textcoords="offset points", xytext=(0, 10 if short else -12),
                    ha="center", fontsize=8, color=sc, fontweight="bold")

    # 4H IFVG + entry / stop / target
    x0, x1 = q - a, k - a
    ax.add_patch(Rectangle((max(0, s1 - a) - 0.4, st["fvg_bottom"]), xmax - max(0, s1 - a) + 0.4,
                           st["fvg_top"] - st["fvg_bottom"], facecolor=BEAR if short else BULL, alpha=0.18, lw=0))
    ax.text(x0, st["fvg_top"] if short else st["fvg_bottom"], " 4H IFVG", fontsize=8, color=BEAR if short else BULL,
            va="bottom" if short else "top")
    for yv, txt, c, ls in ((tr["entry"], f"entry {tr['entry']:.2f}", "black", "-"),
                           (tr["stop"], f"stop {tr['stop']:.2f}", BEAR, "--"),
                           (tr["target"], f"target {tr['target_level']}", BULL, "--")):
        ax.hlines(yv, x0, x1, color=c, ls=ls, lw=1.3)
        ax.text(x1 + 0.5, yv, txt, fontsize=8, color=c, va="center", fontweight="bold")
    ax.plot(x0, tr["entry"], "v" if short else "^", ms=12, mec="black", color=BEAR if short else BULL)
    ax.plot(x1, tr["exit_price"], "X", color="black", ms=10)
    ax.set_title(f"{symbol} #{tr['setup']} {tr['signal'].upper()} swing | swept {tr['swept']} | "
                 f"{tr['entry_time']:%Y-%m-%d %H:%M} | stop {tr['stop_from']} | {tr['exit'].upper()} {tr['r_net']:+.2f}R",
                 fontsize=9)
    _axis(ax, df, "1H")
    ax.set_xlim(-1, len(df) + 12)
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


def run(stop_kind: str = STOP_KIND, ob_type: str = OB_TYPE, target: str = TARGET, ob_pick: str = OB_PICK,
        setups_kind: str = SETUPS, disp_min: int = DISP_MIN_1H, ob_level: str = OB_LEVEL,
        swing_4h_pivot: int | None = None, swing_1h_pivot: int | None = None,
        liq_tfs=None, liq_pivot4: int | None = None, liq_min_rr: float | None = None) -> pd.DataFrame:
    if swing_4h_pivot is None:
        swing_4h_pivot = SWING_4H_PIVOT
    if swing_1h_pivot is None:
        swing_1h_pivot = SWING_1H_PIVOT
    liq_tfs = LIQ_TFS if liq_tfs is None else liq_tfs
    liq_pivot4 = LIQ_4H_PIVOT if liq_pivot4 is None else liq_pivot4
    liq_min_rr = LIQ_MIN_RR if liq_min_rr is None else liq_min_rr
    trades = []
    for symbol, (h1_file, _, _) in SYMBOLS.items():
        h1 = load(DATA / h1_file)
        htf = {tf: build_htf(h1, tf) for tf in ("D", "W", "M")}
        levels = add_break_times(pd.concat([find_swings(htf[tf], tf) for tf in ("M", "W", "D")], ignore_index=True), h1)
        liq = liquidity_levels(h1, levels, liq_tfs, liq_pivot4) if target == "liquidity" else None
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
            why = "never retested the 4H IFVG within 48 h"
            for i in range(q0, q1):
                if (short and o[i] > extreme) or (not short and o[i] < extreme):
                    why = "cancelled: price opened beyond the sweep extreme before the retest"
                    break                                               # rule 4 cancellation
                if (short and h[i] >= level) or (not short and l[i] <= level):
                    q, entry = i, (max(level, o[i]) if short else min(level, o[i]))
                    break
            if q < 0:
                LOST[why] = LOST.get(why, 0) + 1
                continue
            if stop_kind == "4H IFVG":
                base, tag = (st["fvg_top"] if short else st["fvg_bottom"]), "4H IFVG far edge"
            elif stop_kind.startswith("1H FVG beyond IFVG"):
                base, tag = _fvg_beyond_ifvg(st, h1_fvgs, anchor, q, FVG_PICK, FVG_OVERLAP)
                if np.isnan(base):                      # fallback: current 1H OB 50% stop
                    base, tag = _drop_ob(st, h1, h1_fvgs, anchor, q, ob_level)
            elif stop_kind == "1H OB of drop FVG":
                base, tag = _drop_ob(st, h1, h1_fvgs, anchor, q, ob_level)
            else:
                base, tag = stop_level(stop_kind, st, h1, h1_fvgs, h4, anchor, ob_type, ob_pick)
            if np.isnan(base):
                LOST["no stop level"] = LOST.get("no stop level", 0) + 1
                continue
            sl = base + SL_BUFFER[symbol] if short else base - SL_BUFFER[symbol]
            if (short and sl <= entry) or (not short and sl >= entry):
                LOST["stop on the wrong side of the entry (order block below the 4H IFVG)"] = LOST.get("stop on the wrong side of the entry (order block below the 4H IFVG)", 0) + 1
                continue
            risk = abs(entry - sl)
            if target == "3R":
                tp, ttag = (entry - 3 * risk if short else entry + 3 * risk), "3R"
            elif target == "1H swing low":
                tp, ttag = _swing_low_target(st, h1, h4, q), "1H swing low"
                if np.isnan(tp) or (short and tp >= entry) or (not short and tp <= entry):
                    LOST["1H swing-low target not beyond the entry"] = LOST.get("1H swing-low target not beyond the entry", 0) + 1
                    continue
            elif target == "liquidity":
                tp, ttag = liquidity_target(liq, short, entry, risk, idx[q], liq_min_rr)
                if np.isnan(tp):
                    LOST["no opposite liquidity level beyond the entry"] = LOST.get("no opposite liquidity level beyond the entry", 0) + 1
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
            if PLOT:
                OUT.joinpath("trades").mkdir(parents=True, exist_ok=True)
                plot_trade(symbol, trades[-1], st, h1, levels, q, sim["k"],
                           OUT / "trades" / f"{symbol}_{k_st:02d}_{idx[q]:%Y%m%d}_{st['signal']}.png")
    return pd.DataFrame(trades)


if __name__ == "__main__":
    import os
    PLOT = os.environ.get("PLOT", "1") != "0"
    t = run()
    print(f"{len(t)} trades; {'charts in ' + str(OUT / 'trades') if PLOT else 'PLOT off'}")
    pd.set_option("display.width", 250)
    print(t.to_string(index=False) if len(t) else "no trades")
