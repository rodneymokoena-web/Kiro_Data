"""Swing strategy: rules 1-5 (D/W/M sweep -> 4H IFVG -> 1H IFVG), entry on 1H.

Usage:
    .venv/bin/python swing.py                       # both 1H entries (compare)
    .venv/bin/python swing.py --entry 1h-touch      # only 1H touch
    .venv/bin/python swing.py --entry 1h-ce         # only 1H 50% CE
    choices: 1h-touch, 1h-ce, 1h-mss-touch, 1h-mss-ce   (default: ENTRY_FILTER below)

Uses only 1H data (Yahoo 1H goes back to Jan 2025), so every 2026 setup can be tested.
LONG described; SHORT is the mirror image.

ENTRY (1H, limit order valid ENTRY_VALID after the 1H IFVG signal):
    "1H touch" / "1H CE"         limit at the 1H IFVG near edge (top) / 50% midpoint (CE), live from the
                                 first 1H candle after the 1H signal.   <- ENTRY_FILTER chooses between them
    "1H MSS touch" / "1H MSS CE" (optional) after the 1H IFVG is retested, a 1H MSS (or 1H CISD) with displacement
                                 leaves a 1H FVG; limit at its near edge / midpoint (entry_ltf.find_entry on 1H).
    Cancelled if a candle OPENS below the 4H sweep extreme before the fill.
STOP:
    "prev 4H candle" LONG: below the low of the previous COMPLETED 4H candle at the fill time; if that
                    low is not below the entry, the most recent completed 4H candle (up to 24 back) whose low is.
                    SHORT: above the high of the previous 4H candle above the entry.
    "prev 1H swing" LONG: below the previous 1H swing low = the most recent 1H swing low
                    (PREV_SWING_PIVOT candles each side, already confirmed when the order fills) that is
                    below the entry price. SHORT: above the previous 1H swing high above the entry.
    "1H swing"      IFVG entries: below the low of the 1H move that created the 1H IFVG (rule 5 retest -> inversion).
                    MSS FVG entries: below the retest low the MSS broke from.
    "4H OB disp"    (main) below the 4H order block: the last DOWN-close 4H candle before the 4H displacement that
                    inverted the FVG (M6: the last down-close 4H candle of the sweeping leg, completed at the signal).
    "4H extreme"    below the 4H sweep extreme.
    Both minus SL_BUFFER.
TARGET:
    "D/W liquidity" nearest unbroken Daily/Weekly swing high above the entry (known at entry time).
                    No such level -> no trade.
    "3R"            (main) entry + 3 x risk.
MANAGEMENT: once price reaches +1R (from the candle after the fill), the stop moves to breakeven.
EXIT: first 1H candle reaching stop or target; same candle hits both -> stop (conservative).
      On the fill candle only the stop is checked. Still open at the end of the data -> closed at last price.
COSTS: backtest.COST per trade (price units).

Outputs (output/swing/):
    trades.csv, summary.csv, summary_{SYMBOL}.csv, trades/{SYMBOL}_{n}.png (main variant)
"""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

import entry_ltf
import ifvg
import stops_ext
from backtest import COST, SL_BUFFER, prev_candle
from ifvg_1h import build_4h_setups, find_1h_ifvg, signal_key
from ote import BEAR, BULL, _axis
from swings import DATA, SYMBOLS, add_break_times, build_htf, draw_candles, find_swings, load

# ----------------------------------------------------------------------------- CONFIG
ENTRY_VALID = pd.Timedelta(hours=24)        # order valid this long
TARGET_TFS = ("D", "W")                     # external liquidity used as target
TARGET_R = 3.0                              # fixed-R target variant
BE_AT_R = 1.0                                  # move stop to breakeven at +1R; None = off
# Entry filter: any of "1H touch", "1H CE" (1H IFVG near edge / 50% CE), "1H MSS touch", "1H MSS CE"
ENTRY_FILTER = ["1H touch"]                       # main swing model: 1H touch (add "1H CE" to compare)
_ENTRY_KIND = {"1H touch": ("IFVG", "touch"), "1H CE": ("IFVG", "ce"),
               "1H MSS touch": ("MSS", "touch"), "1H MSS CE": ("MSS", "ce")}
_ENTRY_ARG = {"1h-touch": "1H touch", "1h-ce": "1H CE", "1h-mss-touch": "1H MSS touch", "1h-mss-ce": "1H MSS CE"}
STOPS = ["4H OB disp", "4H extreme", "prev 4H candle", "prev 1H swing", "1H swing"]
# extra stops (stops_ext.py): "1H IFVG", "1H FVG above 4H", "4H OB leg", "4H OB disp" - add to STOPS to test
TARGETS = ["D/W liquidity", "3R"]
MAIN_STOP, MAIN_TARGET = "4H OB disp", "3R"   # 4H OB disp = above the last up-close 4H candle before the 4H
                                               # displacement (short); M6: last up-close 4H candle of the sweeping leg        # main stop / target (the main entry = first in ENTRY_FILTER)
PREV_SWING_PIVOT = 2                        # candles each side for the "previous 1H swing" stop
START_BALANCE, RISK_PCT = 10_000, 1.0
# Rule 3 (swing only): "4H close" = default rule 3 "M1" (4H close inverts the 4H FVG, 4H displacement + 1H MSS on the
#        1H swing before the sweep extreme; ifvg_1h.CONFIRM_4H). Used by both models.
# "M6" = optional swing rule: the first 1H candle after the sweep whose low trades below the rule 2 4H FVG (high above,
#        for a long) AND closes below it, with 1H displacement and a 1H MSS = close through the most recent confirmed
#        1H swing low, formed before or after the sweep. No 4H CISD.
#        (setups_v3: INVERT_ON="wick", WICK_CLOSE="through", REQUIRE="mss", MSS_MODE="any"). M6 keeps its own rule 2:
#        the last 4H FVG of any sweeping leg (ifvg.LEG_MODE="any", within 60 4H candles), as tested.
RULE3 = os.environ.get("RULE3", "4H close")

OUT = Path(__file__).parent / "output" / "swing"
H1 = pd.Timedelta(hours=1)


# ----------------------------------------------------------------------------- setups (rules 1-4)
def _swing_setups(h1: pd.DataFrame):
    if RULE3 == "4H close":
        return build_4h_setups(h1)
    if RULE3 != "M6":
        raise ValueError(f"unknown RULE3 {RULE3!r} (use '4H close' or 'M6')")
    import setups_v3 as V3
    keys = ("INVERT_ON", "WICK_CLOSE", "CISD_MODE", "REQUIRE", "WAIT_1H", "MSS_MODE")
    saved = {k: getattr(V3, k) for k in keys}
    saved_leg = (ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK)
    for k, v in zip(keys, ("wick", "through", "1h_close", "mss", 0, "any")):
        setattr(V3, k, v)
    ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK = "any", 60      # M6 keeps its rule 2: last 4H FVG of any sweeping leg
    try:
        return V3.build_setups(h1)
    finally:
        for k, v in saved.items():
            setattr(V3, k, v)
        ifvg.LEG_MODE, ifvg.LEG_MAX_LOOKBACK = saved_leg


# ----------------------------------------------------------------------------- entries
def ifvg_entry(r5: dict, h1: pd.DataFrame, short: bool, mode: str) -> dict:
    o, h, l = h1["Open"].to_numpy(), h1["High"].to_numpy(), h1["Low"].to_numpy()
    idx, n = h1.index, len(h1)
    top, bot = r5["h1_fvg_top"], r5["h1_fvg_bottom"]
    level = (bot if short else top) if mode == "touch" else (top + bot) / 2
    q0, q1 = idx.searchsorted(r5["h1_signal_time"]), min(idx.searchsorted(r5["h1_signal_time"] + ENTRY_VALID), n)
    ext = r5["x"]["extreme"]
    for q in range(q0, q1):
        if (short and o[q] > ext) or (not short and o[q] < ext):
            return {"status": "cancelled (gap beyond 4H extreme)"}
        if (short and h[q] >= level) or (not short and l[q] <= level):
            return {"status": "filled", "q": q, "entry": max(level, o[q]) if short else min(level, o[q])}
    return {"status": "expired"}


def mss_entry(st: dict, r5: dict, h1: pd.DataFrame, h1_fvgs: pd.DataFrame, mode: str) -> dict:
    saved = (entry_ltf.TRIGGER_WINDOW, entry_ltf.FILL_WINDOW)
    entry_ltf.TRIGGER_WINDOW = entry_ltf.FILL_WINDOW = ENTRY_VALID
    try:
        e = entry_ltf.find_entry(st, r5, h1, h1, h1_fvgs, mode, None)   # 1H MSS/CISD, no 5m close-through rule
    finally:
        entry_ltf.TRIGGER_WINDOW, entry_ltf.FILL_WINDOW = saved
    if e["status"] != "filled":
        return {"status": e["status"]}
    return {"status": "filled", "q": e["x"]["entry"], "entry": e["entry_price"], "retest_extreme": e["retest_extreme"],
            "fvg": (e["fvg_bottom"], e["fvg_top"], e["fvg_time"]), "trigger": e["trigger"]}


# ----------------------------------------------------------------------------- stops / targets / sim
def leg_swing(r5: dict, h1: pd.DataFrame, short: bool) -> float:
    """Extreme of the 1H move that created the 1H IFVG: from the rule-5 retest to the inversion candle."""
    a, b = r5["x"]["retest"], r5["x"]["inv_idx"]
    seg = h1.iloc[a:b + 1]
    return seg["High"].max() if short else seg["Low"].min()


def prev_swing(h1: pd.DataFrame, q: int, short: bool, entry: float) -> float:
    """Most recent confirmed 1H swing high (short) / low (long) before candle q, beyond the entry price.
    Swing = highest high / lowest low of the window PREV_SWING_PIVOT candles each side (default 2)."""
    h, l = h1["High"].to_numpy(), h1["Low"].to_numpy()
    p = PREV_SWING_PIVOT
    for i in range(q - p - 1, p - 1, -1):           # confirmed at i + p, which must be before candle q
        win_h, win_l = h[i - p:i + p + 1], l[i - p:i + p + 1]
        if short and h[i] == win_h.max() and h[i] > entry:
            return float(h[i])
        if not short and l[i] == win_l.min() and l[i] < entry:
            return float(l[i])
    return np.nan


def pick_target(levels: pd.DataFrame, short: bool, entry: float, t: pd.Timestamp) -> tuple[float, str]:
    lv = levels[levels["tf"].isin(TARGET_TFS) & (levels["confirmed_time"] <= t)
                & (levels["broken_time"].isna() | (levels["broken_time"] > t))]
    lv = lv[(lv["type"] == "low") & (lv["price"] < entry)] if short else lv[(lv["type"] == "high") & (lv["price"] > entry)]
    if lv.empty:
        return np.nan, ""
    row = lv.loc[lv["price"].idxmax() if short else lv["price"].idxmin()]
    tfs = "/".join(sorted(lv[np.isclose(lv["price"], row["price"])]["tf"].unique(), key="MWD".index))
    return float(row["price"]), f"{tfs}{'L' if short else 'H'} {row['price']:.2f}"


def simulate(h1: pd.DataFrame, q: int, short: bool, entry: float, sl: float, tp: float) -> dict:
    h, l, c = h1["High"].to_numpy(), h1["Low"].to_numpy(), h1["Close"].to_numpy()
    risk = abs(entry - sl)
    stop, be_done = sl, False
    for k in range(q, len(h1)):
        hit_sl = h[k] >= stop if short else l[k] <= stop
        hit_tp = (l[k] <= tp if short else h[k] >= tp) and k > q
        if hit_sl:
            return {"exit": "breakeven" if be_done else "stop", "k": k, "price": stop, "be": be_done}
        if hit_tp:
            return {"exit": "target", "k": k, "price": tp, "be": be_done}
        if BE_AT_R is not None and not be_done and k > q:
            if (short and l[k] <= entry - BE_AT_R * risk) or (not short and h[k] >= entry + BE_AT_R * risk):
                stop, be_done = entry, True
    return {"exit": "open", "k": len(h1) - 1, "price": c[-1], "be": be_done}


# ----------------------------------------------------------------------------- chart (main variant)
def plot_trade(symbol: str, tr: dict, h1: pd.DataFrame, r5: dict, path: Path) -> None:
    short = tr["signal"] == "short"
    q, k = tr["x_q"], tr["x_k"]
    a, b = max(0, r5["x"]["anchor"] - 15), min(len(h1), k + 20)
    df = h1.iloc[a:b]
    fig, ax = plt.subplots(figsize=(16, 6.5))
    draw_candles(ax, df)
    xs = h1.index.searchsorted(r5["h1_signal_time"]) - a
    ax.add_patch(Rectangle((xs - 1.4, r5["h1_fvg_bottom"]), k - a - xs + 1.4, r5["h1_fvg_top"] - r5["h1_fvg_bottom"],
                           facecolor=BEAR if short else BULL, alpha=0.3, hatch="xx", lw=0))
    ax.text(xs - 1, r5["h1_fvg_top"] if short else r5["h1_fvg_bottom"], " 1H IFVG", fontsize=8,
            va="bottom" if short else "top", color=BEAR if short else BULL)
    x0, x1 = q - a, k - a
    for y, txt, col, ls in ((tr["entry"], f"entry {tr['entry']:.2f}", "black", "-"),
                            (tr["stop"], f"stop {tr['stop']:.2f}", BEAR, "--"),
                            (tr["target"], f"target {tr['target_level']}", BULL, "--")):
        ax.hlines(y, x0, x1, color=col, ls=ls, lw=1.3)
        ax.text(x1 + 1, y, txt, fontsize=8, color=col, va="center", fontweight="bold")
    ax.fill_between([x0, x1], tr["entry"], tr["target"], color=BULL, alpha=0.07)
    ax.fill_between([x0, x1], tr["entry"], tr["stop"], color=BEAR, alpha=0.07)
    ax.plot(x0, tr["entry"], "v" if short else "^", ms=12, mec="black", color=BEAR if short else BULL)
    ax.plot(x1, tr["exit_price"], "X", color="black", ms=10)
    ax.set_title(f"{symbol} #{tr['setup']} {tr['signal'].upper()} swing (1H) | {tr['entry_type']} / stop {tr['stop_type']} / "
                 f"target {tr['target_type']} | {tr['entry_time']:%Y-%m-%d %H:%M} -> {tr['exit_time']:%Y-%m-%d %H:%M} | "
                 f"planned {tr['planned_rr']:.1f}R | {tr['exit'].upper()} {tr['r_net']:+.2f}R", fontsize=9)
    _axis(ax, df, "1H")
    ax.set_xlim(-1, len(df) + 14)
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


# ----------------------------------------------------------------------------- run
def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    (OUT / "trades").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "trades").glob("*.png"):
        old.unlink()
    trades, skipped = [], []
    for symbol, (h1_file, _, _) in SYMBOLS.items():
        h1 = load(DATA / h1_file)
        htf = {tf: build_htf(h1, tf) for tf in ("D", "W", "M")}
        levels = add_break_times(pd.concat([find_swings(htf[tf], tf) for tf in ("M", "W", "D")], ignore_index=True), h1)
        h4, setups = _swing_setups(h1)
        h4c = build_htf(h1, "4H")                  # 4H candles with real close times (for the "prev 4H candle" stop)
        h1_fvgs = ifvg.find_fvgs(h1)
        seen_1h = set()
        for n, st in enumerate(setups, 1):
            r5 = find_1h_ifvg(st, h1, h1_fvgs)
            short = st["signal"] == "short"
            if r5["status"] != "signal":
                skipped.append({"symbol": symbol, "setup": n, "variant": "all", "reason": f"no 1H IFVG ({r5['status']})"})
                continue
            if signal_key(st, r5) in seen_1h:          # same 1H IFVG already traded via another 4H setup
                skipped.append({"symbol": symbol, "setup": n, "variant": "all", "reason": "duplicate 1H IFVG signal"})
                continue
            seen_1h.add(signal_key(st, r5))
            for etype in ENTRY_FILTER:
                kind, mode = _ENTRY_KIND[etype]
                e = ifvg_entry(r5, h1, short, mode) if kind == "IFVG" else mss_entry(st, r5, h1, h1_fvgs, mode)
                if e["status"] != "filled":
                    skipped.append({"symbol": symbol, "setup": n, "variant": etype, "reason": e["status"]})
                    continue
                entry, q = e["entry"], e["q"]
                for stype in STOPS:
                    if stype == "prev 4H candle":
                        base_sl = prev_candle(h4c, h1.index[q], pd.Timedelta(hours=4), short, entry, 24)
                    elif stype == "prev 1H swing":
                        base_sl = prev_swing(h1, q, short, entry)
                    elif stype == "1H swing":
                        base_sl = leg_swing(r5, h1, short) if kind == "IFVG" else e["retest_extreme"]
                    elif stype in stops_ext.KINDS:
                        base_sl = stops_ext.level(stype, st, r5, h1_fvgs, h4, h1, entry)
                    else:
                        base_sl = r5["x"]["extreme"]
                    if np.isnan(base_sl):
                        skipped.append({"symbol": symbol, "setup": n, "variant": f"{etype} / {stype}",
                                        "reason": "no previous swing beyond entry"})
                        continue
                    sl = base_sl + SL_BUFFER[symbol] if short else base_sl - SL_BUFFER[symbol]
                    risk = abs(entry - sl)
                    if (short and sl <= entry) or (not short and sl >= entry):
                        skipped.append({"symbol": symbol, "setup": n, "variant": f"{etype} / {stype}",
                                        "reason": "stop on wrong side of entry"})
                        continue
                    for ttype in TARGETS:
                        if ttype == "3R":
                            tp, tag = (entry - TARGET_R * risk if short else entry + TARGET_R * risk), f"{TARGET_R:g}R"
                        else:
                            tp, tag = pick_target(levels, short, entry, h1.index[q])
                            if np.isnan(tp):
                                skipped.append({"symbol": symbol, "setup": n, "variant": f"{etype} / {stype} / {ttype}",
                                                "reason": "no unbroken D/W level beyond entry"})
                                continue
                        sim = simulate(h1, q, short, entry, sl, tp)
                        pnl = (entry - sim["price"]) if short else (sim["price"] - entry)
                        tr = {"symbol": symbol, "setup": n, "signal": st["signal"], "entry_type": etype, "stop_type": stype,
                              "target_type": ttype, "4h_signal_time": st["signal_time"], "1h_signal_time": r5["h1_signal_time"],
                              "entry_time": h1.index[q], "entry": entry, "stop": sl, "target": tp, "target_level": tag,
                              "risk_pts": risk, "planned_rr": abs(tp - entry) / risk, "exit": sim["exit"],
                              "exit_time": h1.index[sim["k"]], "exit_price": sim["price"], "moved_to_be": sim["be"],
                              "hours_held": (h1.index[sim["k"]] - h1.index[q]).total_seconds() / 3600,
                              "pnl_pts": pnl, "r_net": (pnl - COST[symbol]) / risk, "x_q": q, "x_k": sim["k"],
                              "stop_fallback": stype.startswith("1H OB") and stops_ext.last_fallback}
                        trades.append(tr)
                        if (etype, stype, ttype) == main_variant():
                            plot_trade(symbol, tr, h1, r5, OUT / "trades" / f"{symbol}_{n:02d}.png")
    t = pd.DataFrame(trades)
    t[[c for c in t.columns if not c.startswith("x_")]].to_csv(OUT / "trades.csv", index=False)
    s = pd.DataFrame(skipped)
    s.to_csv(OUT / "not_traded.csv", index=False)
    return t, s


def stats(g: pd.DataFrame) -> dict:
    closed = g[g["exit"] != "open"]
    win, loss = g.loc[g["r_net"] > 0, "r_net"].sum(), abs(g.loc[g["r_net"] < 0, "r_net"].sum())
    eq, peak, mdd = START_BALANCE, START_BALANCE, 0.0
    for r in g.sort_values("entry_time")["r_net"]:
        eq += eq * RISK_PCT / 100 * r
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
    return {"trades": len(g), "wins": int((g["exit"] == "target").sum()), "losses": int((g["exit"] == "stop").sum()),
            "breakeven": int((g["exit"] == "breakeven").sum()), "open": int((g["exit"] == "open").sum()),
            "win_rate_%": round(100 * (closed["exit"] == "target").mean(), 1) if len(closed) else np.nan,
            "profit_factor": round(win / loss, 2) if loss > 0 else float("inf"),
            "total_R": round(g["r_net"].sum(), 2), "avg_R": round(g["r_net"].mean(), 2),
            "avg_planned_RR": round(g["planned_rr"].mean(), 2), "avg_hours_held": round(g["hours_held"].mean(), 1),
            f"end_balance_{RISK_PCT:g}%": round(eq, 2), "max_dd_%": round(mdd, 2)}


def main_variant() -> tuple[str, str, str]:
    return ENTRY_FILTER[0], MAIN_STOP, MAIN_TARGET


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t, s = run()
    rows = []
    for (e, st_, tg), g in t.groupby(["entry_type", "stop_type", "target_type"]):
        for sym in ["ALL"] + sorted(t["symbol"].unique()):
            gg = g if sym == "ALL" else g[g["symbol"] == sym]
            if len(gg):
                rows.append({"entry": e, "stop": st_, "target": tg, "symbol": sym, **stats(gg)})
    summ = pd.DataFrame(rows)
    summ.to_csv(OUT / "summary.csv", index=False)
    for sym in sorted(t["symbol"].unique()):
        summ[summ["symbol"] == sym].to_csv(OUT / f"summary_{sym}.csv", index=False)
        t[t["symbol"] == sym][[c for c in t.columns if not c.startswith("x_")]].to_csv(OUT / f"trades_{sym}.csv", index=False)
    pd.set_option("display.width", 250)
    MAIN = main_variant()
    print("ENTRY FILTER:", ", ".join(ENTRY_FILTER))
    for ent in ENTRY_FILTER:
        m = summ[(summ.entry == ent) & (summ.stop == MAIN[1]) & (summ.target == MAIN[2])]
        print(f"\n{ent} / {MAIN[1]} / {MAIN[2]}:")
        print(m.drop(columns=["entry", "stop", "target"]).to_string(index=False))
    m = summ[(summ.entry == MAIN[0]) & (summ.stop == MAIN[1]) & (summ.target == MAIN[2])]
    print("\nMAIN VARIANT:", " / ".join(MAIN))
    print(m.drop(columns=["entry", "stop", "target"]).to_string(index=False))
    print("\nALL VARIANTS (per symbol):")
    print(summ[summ.symbol != "ALL"][["entry", "stop", "target", "symbol", "trades", "wins", "losses", "breakeven",
                                      "win_rate_%", "profit_factor", "total_R"]].to_string(index=False))
    print("\nNot traded:", s.groupby("symbol")["reason"].value_counts().to_dict())


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", nargs="+", choices=list(_ENTRY_ARG), default=None,
                    help="swing entries to test, e.g. --entry 1h-touch or --entry 1h-ce (default: ENTRY_FILTER)")
    a = ap.parse_args()
    if a.entry:
        ENTRY_FILTER = [_ENTRY_ARG[x] for x in a.entry]
    main()
