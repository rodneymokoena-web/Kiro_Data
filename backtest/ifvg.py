"""Rule 2: Liquidity sweep of D/W/M swing levels -> FVG left in the leg -> FVG gets inverted (IFVG).

Usage:
    .venv/bin/python ifvg.py

Logic (per display timeframe D / 4H / 1H / 15m / 5m):
    1. SWEEP      A DAILY candle trades through a relative equal high / low from rule 1 (buy-side / sell-side
                  stops; SWEEP_TFS = ("D",)). The sweep moment is pinned to the 4H candle in which it happens.
    2. LEG        LEG_MODE="swing": the leg starts at the last 4H swing low (high sweep) / swing high (low sweep)
                  before the sweep, LEG_PIVOT candles each side. LEG_MODE="lookback": lowest low / highest high
                  of the LEG_LOOKBACK candles before the sweep.
    3. FVG        FVG_SELECT="last": the LAST 3-candle FVG of the sweeping leg = the leg from the last 4H swing to
                  the D/W/M sweep candle - only that one may be inverted. FVG_SELECT="first": any FVG
                  of the leg, the first one inverted counts. Direction of the leg:
                    bullish FVG: Low[c3] > High[c1]   zone = High[c1] .. Low[c3]
                    bearish FVG: High[c3] < Low[c1]   zone = High[c3] .. Low[c1]
                  Formed INTO the sweep (FVG_INTO_SWEEP: middle candle at or before the sweep candle) and
                  not closed through before the sweep.
    4. INVERSION  Within INVERT_WINDOW bars after the sweep, a candle CLOSES through the FVG
                  the other way:
                    high swept -> close below a bullish FVG -> bearish IFVG -> SHORT signal
                    low swept  -> close above a bearish FVG -> bullish IFVG -> LONG signal
                  The first inversion after the sweep is the signal. If one candle inverts
                  several FVGs at once, the one nearest to price is used.
    The signal is known at the CLOSE of the inversion candle (no look-ahead).

Outputs:
    output/ifvg/{SYMBOL}_ifvg_signals.csv   every setup (all timeframes)
    output/ifvg/{SYMBOL}_{tf}.png           charts with sweeps, FVGs and IFVGs
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from swings import (DATA, STYLE, SYMBOLS, TEST_START, add_break_times, build_htf, draw_candles,
                    find_swings, load, refine_breaks)

# ----------------------------------------------------------------------------- CONFIG
LEG_LOOKBACK = 20      # bars before the sweep to find where the leg started ("lookback" leg mode)
# Rule 2 (revised)
SWEEP_TFS = ("M", "W", "D")   # rule 1 liquidity: swing levels whose sweep starts a setup; add "4H" for 4H swings
SESSION_TFS = ()              # session liquidity (e.g. ("ASIA","LONDON","NY")); swept like swing levels
SIG_4H = False                # True = 4H liquidity = only significant 4H swings (swings.significant_4h_levels)
import os as _os
RULE1_4H_PIVOT = int(_os.environ.get("RULE1_4H_PIVOT", "10"))   # 4H swing size: 10 = major swings (default), 2 = all swings
LEG_MODE = "swing"     # default rule 2: "swing" = leg from the last 4H swing; "any" = any leg sweeping the D/W/M level
                       # (used by the swing option M6); "lookback"
                       # "lookback" = lowest low (highest high) of the LEG_LOOKBACK candles before the sweep
LEG_PIVOT = 2
LEG_MAX_LOOKBACK = 60  # "any" leg mode: the last FVG may be at most this many 4H candles before the sweep
FVG_SELECT = "first"   # default rule 2 FVG: "first" = first inverted FVG of the leg (formed into the sweep, below);
                       #   "last" = only the LAST FVG formed on the leg sweeping the D/W/M level (impulse candle at or
                       #   before the sweep candle, intact at the sweep)
FVG_INTO_SWEEP = True  # "first" only: FVG must be formed into the sweep (its middle candle at or before the sweep candle)
INVERT_WINDOW = 20     # bars after the sweep in which the FVG must be inverted
MIN_FVG_ATR = 0.0      # minimum FVG height as a fraction of ATR(14); 0 = keep every FVG
IFVG_EXTEND = 30       # bars to draw the IFVG zone after inversion (stops early if invalidated)

OUT = Path(__file__).parent / "output" / "ifvg"
DISPLAY_WINDOW = {"D": None, "4H": pd.Timedelta(days=120), "1H": pd.Timedelta(days=30),
                  "15m": pd.Timedelta(days=14), "5m": pd.Timedelta(days=5)}
BULL, BEAR = "#26a69a", "#ef5350"


# ----------------------------------------------------------------------------- detection
def atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean().to_numpy()


def find_fvgs(df: pd.DataFrame) -> pd.DataFrame:
    """All 3-candle FVGs. idx = index of candle 3 (FVG confirmed at its close).
    inv_idx = first later bar that closes through the FVG the opposite way (-1 if never)."""
    h, l, c = df["High"].to_numpy(), df["Low"].to_numpy(), df["Close"].to_numpy()
    min_size = atr(df) * MIN_FVG_ATR
    rows = []
    for i in range(2, len(df)):
        if l[i] > h[i - 2] and l[i] - h[i - 2] >= min_size[i]:
            rows.append(("bull", i, h[i - 2], l[i]))
        if h[i] < l[i - 2] and l[i - 2] - h[i] >= min_size[i]:
            rows.append(("bear", i, h[i], l[i - 2]))
    fvgs = pd.DataFrame(rows, columns=["dir", "idx", "bottom", "top"])
    inv = []
    for d, i, bot, top in fvgs.itertuples(index=False):
        later = c[i + 1:]
        hit = later < bot if d == "bull" else later > top
        inv.append(i + 1 + int(np.argmax(hit)) if hit.any() else -1)
    fvgs["inv_idx"] = inv
    return fvgs


def leg_origin(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray, s: int, high_swept: bool) -> int:
    """Index of the first candle of the leg into the sweep candle s (-1 = no leg)."""
    if LEG_MODE == "any":
        # any leg that sweeps the level: no fixed start; the FVG only has to be on the move into the sweep
        # (intact at the sweep) and within LEG_MAX_LOOKBACK 4H candles of it
        return max(0, s - LEG_MAX_LOOKBACK)
    if LEG_MODE == "lookback":
        lo = max(0, s - LEG_LOOKBACK)
        return lo + int(np.argmin(l[lo:s + 1]) if high_swept else np.argmax(h[lo:s + 1]))
    if LEG_MODE == "swing":
        p = LEG_PIVOT
        for i in range(s - p, p - 1, -1):         # confirmed by candle i + p <= s
            if high_swept and l[i] == l[i - p:i + p + 1].min():
                return i
            if not high_swept and h[i] == h[i - p:i + p + 1].max():
                return i
        return -1
    raise ValueError(f"unknown LEG_MODE {LEG_MODE!r} (use 'any', 'swing' or 'lookback')")


def find_setups(bars: pd.DataFrame, levels: pd.DataFrame, tf: str, accept=None) -> pd.DataFrame:
    """Sweep -> FVG in leg -> inversion. `levels` must carry broken_time computed on `bars`.
    accept(bars, fvg_row, sweep_idx, fvg_dir) -> dict, optional quality filter: the first inversion
    whose dict has passed=True is used (extra keys are stored on the setup)."""
    o, h, l, c = (bars[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    n = len(bars)
    fvgs = find_fvgs(bars)
    swept = levels[levels["broken_time"].notna() & (levels["broken_time"] >= max(TEST_START, bars.index[0]))
                   & levels["tf"].isin(tuple(SWEEP_TFS) + tuple(SESSION_TFS))]

    setups: dict[tuple, dict] = {}
    for lv in swept.itertuples(index=False):
        s = bars.index.get_indexer([lv.broken_time])[0]
        if s < 0:
            continue
        # buy-side liquidity taken -> bullish FVG of the leg up gets inverted (short); mirror for sell-side
        want, signal = ("bull", "short") if lv.type == "high" else ("bear", "long")
        origin = leg_origin(o, h, l, c, s, lv.type == "high")
        if origin < 0:
            continue
        f, info = None, {}
        if FVG_SELECT == "last":
            # LAST FVG of the sweeping leg = leg from the last 4H swing (origin) to the D/W/M sweep candle s.
            # "Last" = the most recent FVG whose impulse (middle) candle is at or before the sweep candle.
            # Only that one FVG may be inverted (4H close through it within INVERT_WINDOW, with the quality check).
            legf = fvgs[(fvgs["dir"] == want) & (fvgs["idx"] - 2 >= origin) & (fvgs["idx"] - 1 <= s)
                        & ((fvgs["inv_idx"] < 0) | (fvgs["inv_idx"] >= s))]
            if not legf.empty:
                row = legf.loc[legf["idx"].idxmax()]
                jv = int(row["inv_idx"])
                if s <= jv <= min(s + INVERT_WINDOW, n - 1) and jv > int(row["idx"]):
                    info = accept(bars, row, s, want) if accept is not None else {}
                    if info.get("passed", True):
                        f = row
        else:
            cand = fvgs[(fvgs["dir"] == want) & (fvgs["idx"] - 2 >= origin) & (fvgs["inv_idx"] >= s)
                        & (fvgs["inv_idx"] <= min(s + INVERT_WINDOW, n - 1)) & (fvgs["inv_idx"] > fvgs["idx"])]
            if FVG_INTO_SWEEP:
                cand = cand[cand["idx"] - 1 <= s]      # formed into taking the highs/lows
            # earliest inversion first; same candle -> nearest to price (lowest bull FVG / highest bear FVG)
            cand = cand.sort_values(["inv_idx", "bottom" if want == "bull" else "top"],
                                    ascending=[True, want == "bull"])
            for _, row in cand.iterrows():
                info = accept(bars, row, s, want) if accept is not None else {}
                if info.get("passed", True):
                    f = row
                    break
        if f is None:
            continue
        key = (int(f["idx"]), want)
        tag = f"{lv.tf}{'H' if lv.type == 'high' else 'L'} {lv.price:.2f}"
        if key in setups:  # same IFVG produced by several swept levels -> merge
            if tag not in setups[key]["swept_levels"]:
                setups[key]["swept_levels"] += f", {tag}"
            setups[key]["sweep_time"] = min(setups[key]["sweep_time"], lv.broken_time)
            continue
        j = int(f["inv_idx"])
        setups[key] = {
            "tf": tf, "signal": signal, "swept_levels": tag,
            "sweep_time": lv.broken_time,
            "fvg_time": bars.index[int(f["idx"]) - 2], "fvg_bottom": f["bottom"], "fvg_top": f["top"],
            "inversion_time": bars.index[j], "inversion_close": c[j],
            "x_fvg_idx": int(f["idx"]), "x_inv_idx": j, "x_sweep_idx": s,
            "x_levels": [(lv.tf, lv.type, lv.price, lv.confirmed_time)],
            **info,
        }
    out = pd.DataFrame(setups.values())
    return out.sort_values("inversion_time").reset_index(drop=True) if len(out) else out


# ----------------------------------------------------------------------------- plotting
def plot(symbol: str, tf: str, bars: pd.DataFrame, setups: pd.DataFrame, levels: pd.DataFrame, path: Path) -> int:
    window = DISPLAY_WINDOW[tf]
    end = bars.index[-1]
    start = max(TEST_START, end - window) if window is not None else TEST_START
    off = int(bars.index.searchsorted(start))
    df = bars.iloc[off:]
    if df.empty:
        return 0
    c = bars["Close"].to_numpy()
    pad = (df["High"].max() - df["Low"].min()) * 0.08
    ymin, ymax = df["Low"].min() - pad, df["High"].max() + pad

    fig, ax = plt.subplots(figsize=(18, 8))
    draw_candles(ax, df)
    shown = setups[setups["x_inv_idx"] >= off] if len(setups) else setups

    # swept levels (line up to the sweep candle)
    for lv in levels.itertuples(index=False):
        if pd.isna(lv.broken_time) or lv.broken_time < df.index[0] or not (ymin <= lv.price <= ymax):
            continue
        s = int(bars.index.get_indexer([lv.broken_time])[0]) - off
        x0 = max(int(bars.index.searchsorted(lv.confirmed_time)) - off, 0)
        colour, lw = STYLE[lv.tf]
        ax.hlines(lv.price, x0, s, color=colour, lw=lw * 0.8, ls="-" if lv.type == "high" else "--", alpha=0.55)
        ax.plot(s, lv.price, marker="x", color=colour, ms=7, mew=2)

    for st in shown.itertuples(index=False):
        i3, j = st.x_fvg_idx - off, st.x_inv_idx - off
        i1 = i3 - 2
        bull_fvg = st.signal == "short"
        # original FVG: from candle 1 to the inversion candle
        ax.add_patch(Rectangle((max(i1, 0) - 0.4, st.fvg_bottom), j - max(i1, 0) + 0.4, st.fvg_top - st.fvg_bottom,
                               color=BULL if bull_fvg else BEAR, alpha=0.25, lw=0))
        # IFVG: from inversion until price closes back through the other side (or IFVG_EXTEND bars)
        k_end = min(st.x_inv_idx + IFVG_EXTEND, len(bars) - 1)
        for k in range(st.x_inv_idx + 1, k_end + 1):
            if (bull_fvg and c[k] > st.fvg_top) or (not bull_fvg and c[k] < st.fvg_bottom):
                k_end = k
                break
        ax.add_patch(Rectangle((j - 0.4, st.fvg_bottom), k_end - st.x_inv_idx + 0.8, st.fvg_top - st.fvg_bottom,
                               facecolor=BEAR if bull_fvg else BULL, alpha=0.45, hatch="///", lw=0.8,
                               edgecolor=BEAR if bull_fvg else BULL))
        ax.text(j + 0.5, st.fvg_top if bull_fvg else st.fvg_bottom, "IFVG", fontsize=7, fontweight="bold",
                color=BEAR if bull_fvg else BULL, va="bottom" if bull_fvg else "top")
        # signal marker on the inversion candle
        y = bars["High"].iat[st.x_inv_idx] + pad * 0.25 if bull_fvg else bars["Low"].iat[st.x_inv_idx] - pad * 0.25
        ax.plot(j, y, marker="v" if bull_fvg else "^", color=BEAR if bull_fvg else BULL, ms=10)

    step = max(len(df) // 12, 1)
    ticks = list(range(0, len(df), step))
    fmt = "%Y-%m-%d" if tf in ("D", "4H") else "%m-%d %H:%M"
    ax.set_xticks(ticks)
    ax.set_xticklabels([df.index[i].strftime(fmt) for i in ticks], rotation=30, ha="right", fontsize=8)
    ax.set_xlim(-1, len(df) + 2)
    ax.set_ylim(ymin, ymax)
    ax.grid(alpha=0.15)
    n_s, n_l = int((shown["signal"] == "short").sum()) if len(shown) else 0, int((shown["signal"] == "long").sum()) if len(shown) else 0
    ax.set_title(f"{symbol} {tf} | {df.index[0]:%Y-%m-%d %H:%M} -> {df.index[-1]:%Y-%m-%d %H:%M} UTC | "
                 f"D/W/M sweep -> IFVG: {n_s} short, {n_l} long", fontsize=11)
    legend = [plt.Line2D([], [], color=STYLE[k][0], lw=2, label=f"{name} level swept")
              for k, name in (("M", "Monthly"), ("W", "Weekly"), ("D", "Daily"))]
    legend += [Rectangle((0, 0), 1, 1, color=BULL, alpha=0.25, label="Bullish FVG (before inversion)"),
               Rectangle((0, 0), 1, 1, color=BEAR, alpha=0.25, label="Bearish FVG (before inversion)"),
               Rectangle((0, 0), 1, 1, facecolor=BEAR, alpha=0.45, hatch="///", label="Bearish IFVG"),
               Rectangle((0, 0), 1, 1, facecolor=BULL, alpha=0.45, hatch="///", label="Bullish IFVG"),
               plt.Line2D([], [], color=BEAR, marker="v", ls="", label="Short signal"),
               plt.Line2D([], [], color=BULL, marker="^", ls="", label="Long signal")]
    ax.legend(handles=legend, loc="upper left", fontsize=7, ncol=5)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return len(shown)


# ----------------------------------------------------------------------------- main
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for symbol, (h1_file, m15_file, m5_file) in SYMBOLS.items():
        h1 = load(DATA / h1_file)
        htf = {tf: build_htf(h1, tf) for tf in ("D", "W", "M", "4H")}
        levels = pd.concat([find_swings(htf[tf], tf) for tf in ("M", "W", "D")], ignore_index=True)
        levels_1h = add_break_times(levels, h1)

        display = {"D": htf["D"].drop(columns=["Start", "End"]), "4H": htf["4H"].drop(columns=["Start", "End"]),
                   "1H": h1, "15m": load(DATA / m15_file), "5m": load(DATA / m5_file)}
        all_setups = []
        print(f"\n{symbol}")
        for tf, bars in display.items():
            if tf in ("D", "4H"):
                lv = add_break_times(levels, bars)
            elif tf == "1H":
                lv = levels_1h
            else:
                lv = refine_breaks(levels_1h, bars)
            setups = find_setups(bars, lv, tf)
            n_drawn = plot(symbol, tf, bars, setups, lv, OUT / f"{symbol}_{tf}.png")
            if len(setups):
                all_setups.append(setups)
                n_short, n_long = (setups.signal == "short").sum(), (setups.signal == "long").sum()
            else:
                n_short = n_long = 0
            print(f"  {tf:>3}: {len(setups):3d} IFVG signals ({n_short} short / {n_long} long) "
                  f"from {bars.index[0]:%Y-%m-%d} | {n_drawn} on chart -> output/ifvg/{symbol}_{tf}.png")
        if all_setups:
            res = pd.concat(all_setups, ignore_index=True)
            res = res[[c for c in res.columns if not c.startswith("x_")]]
            res.to_csv(OUT / f"{symbol}_ifvg_signals.csv", index=False)


if __name__ == "__main__":
    main()
