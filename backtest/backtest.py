"""Rule 7: stop loss beyond the 15m/5m entry FVG, target 2R. Full backtest.

Usage:
    .venv/bin/python backtest.py                            # all four entries
    .venv/bin/python backtest.py --entry 5m-touch           # one entry
    .venv/bin/python backtest.py --entry 15m-touch 5m-ce    # any combination
    choices: 15m-touch, 15m-ce, 5m-touch, 5m-ce, all   (default: ENTRY_FILTER in entry_ltf.py)

Pipeline: rules 1-6 (swings -> 4H IFVG -> 1H IFVG -> 15m/5m MSS + entry FVG), then:
    STOP    STOP_MODE="prev_1h_candle" (default): beyond the high (short) / low (long) of the previous COMPLETED
            1H candle at the fill time; if that level is not beyond the entry, the most recent completed 1H
            candle (up to PREV_CANDLE_LOOKBACK back) whose high/low is beyond the entry. +/- SL_BUFFER.
            STOP_MODE="prev_swing": beyond the previous swing high (short) / low (long) on the entry
            timeframe (5m or 15m) = the most recent swing (PREV_SWING_PIVOT candles each side) already confirmed
            when the order fills and beyond the entry price, +/- SL_BUFFER.
            STOP_MODE="4h_extreme": beyond the 4H sweep extreme.  STOP_MODE="fvg": beyond the entry FVG.
            STOP_MODE in stops_ext.KINDS ("1H IFVG", "1H FVG above 4H", "4H OB leg", "4H OB disp"): see stops_ext.py.
    TARGET  TARGET_R x risk from the entry price (default 3R).
    BE      once price reaches +BE_AT_R x risk (from the candle after the fill), the stop moves to the entry.
    EXIT    First bar (entry timeframe) that reaches the stop or the target.
            Same bar hits both -> counted as a STOP (intra-bar order unknown, conservative).
            On the fill bar itself only the stop is checked.
            Still open at the end of the data -> closed at the last price (marked "open").
    COSTS   COST (spread + commission, price units) is subtracted from every trade.

Results are in R (1R = entry-to-stop distance), plus an equity example at RISK_PCT per trade.

Outputs:
    output/backtest/trades.csv
    output/backtest/summary.csv
    output/backtest/trades/{SYMBOL}_{n}_{tf}_{mode}.png
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import entry_ltf
import ifvg
import stops_ext
from entry_ltf import find_entry
from ifvg_1h import build_4h_setups, find_1h_ifvg, signal_key
from ote import BEAR, BULL, _axis
from matplotlib.patches import Rectangle

from swings import DATA, DATA_SOURCE, SYMBOLS, draw_candles, load

# ----------------------------------------------------------------------------- CONFIG
SL_BUFFER = {"US100": 2.0, "XAUUSD": 0.5, "US500": 0.6, "US30": 4.5, "DE30": 2.0, "UK100": 1.0, "JP225": 4.0}   # price units beyond the stop level (~0.01% of price)
# round-trip cost per trade, price units: broker data = median spread of the export (data/{source}/costs.json,
# written by fetch_goat.py; no commission included); Yahoo = estimate
_costs = DATA / "costs.json"
COST = json.loads(_costs.read_text()) if DATA_SOURCE != "yahoo" and _costs.exists() else {"US100": 1.0, "XAUUSD": 0.3}
# Rule 7 (same settings as the best swing version). Set STOP_MODE="fvg", TARGET_R=2.0, BE_AT_R=None for the
# previous intraday rule 7.
# Rule 1 for the intraday model: liquidity = 4H swings (INTRADAY_4H_PIVOT candles each side, only the significant 4H
# highs/lows) + D/W/M swings (2 each side). The swing model keeps D/W/M (ifvg.SWEEP_TFS).
INTRADAY_LIQ_TFS = ("M", "W", "D", "4H")
INTRADAY_4H_PIVOT = 10
# How a 4H swing sweep is traded: "4H FVG" = like D/W/M (4H FVG -> 4H IFVG -> retest -> 1H IFVG);
# "1H FVG" = rule 1b: 1H FVG of the leg inverted -> 1H IFVG straight away (setups_v2, no 4H step).
INTRADAY_4H_MODE = "4H FVG"
INTRADAY_1H_PIVOT = 0   # rule 1c: 1H swing sweeps -> 1H FVG of the leg -> 1H IFVG (setups_v2), 0 = off
# extra layers on top of the above: [(level tf, pivot)], each traded via 1H FVG -> 1H IFVG, only at a POI
# (4H sweep into a D FVG, 1H sweep into a 4H FVG). [] = off.
INTRADAY_POI_LAYERS: list = []
STOP_MODE = "prev_1h_candle"                   # "prev_1h_candle" = beyond the previous completed 1H candle's high/low
                                               # "prev_swing" = beyond the previous 5m/15m swing (entry TF)
                                               # "4h_extreme" = beyond the 4H sweep extreme | "fvg" = beyond the entry FVG
PREV_SWING_PIVOT = 2                           # swing size for "prev_swing" (candles each side)
PREV_CANDLE_LOOKBACK = 24                      # candles searched back for "prev_1h_candle"
TARGET_R = 3.0                                 # take profit at this multiple of the risk
BE_AT_R = 1.0                                  # move stop to breakeven at +1R; None = off
START_BALANCE = 10_000
RISK_PCT = 1.0

OUT = Path(__file__).parent / "output" / "backtest"


# ----------------------------------------------------------------------------- trade logic
def prev_candle(htf: pd.DataFrame, t_fill: pd.Timestamp, bar: pd.Timedelta, short: bool, entry: float,
                lookback: int) -> float:
    """High (short) / low (long) of the previous COMPLETED higher-TF candle at t_fill that is beyond the entry.
    htf is indexed by candle open time; a candle is complete when its close (the "End" column if present,
    else open + bar) is <= t_fill."""
    if "End" in htf.columns:
        k = int(pd.DatetimeIndex(htf["End"]).searchsorted(t_fill, side="right")) - 1
    else:
        k = htf.index.searchsorted(t_fill - bar, side="right") - 1  # last candle with close <= t_fill
    for i in range(k, max(k - lookback, -1), -1):
        px = htf["High"].iat[i] if short else htf["Low"].iat[i]
        if (short and px > entry) or (not short and px < entry):
            return float(px)
    return np.nan


def prev_swing(bars: pd.DataFrame, q: int, short: bool, entry: float) -> float:
    """Most recent confirmed swing high (short) / low (long) before candle q, beyond the entry price."""
    h, l = bars["High"].to_numpy(), bars["Low"].to_numpy()
    p = PREV_SWING_PIVOT
    for i in range(q - p - 1, p - 1, -1):           # confirmed at i + p, which must be before candle q
        if short and h[i] == h[i - p:i + p + 1].max() and h[i] > entry:
            return float(h[i])
        if not short and l[i] == l[i - p:i + p + 1].min() and l[i] < entry:
            return float(l[i])
    return np.nan


def simulate(ltf: pd.DataFrame, q: int, short: bool, entry: float, sl: float, tp: float) -> dict:
    h, l, c = ltf["High"].to_numpy(), ltf["Low"].to_numpy(), ltf["Close"].to_numpy()
    risk = abs(entry - sl)
    stop, be = sl, False
    for k in range(q, len(ltf)):
        hit_sl = h[k] >= stop if short else l[k] <= stop
        hit_tp = (l[k] <= tp if short else h[k] >= tp) and k > q
        if hit_sl:
            return {"exit": "breakeven" if be else "stop", "exit_idx": k, "exit_price": stop}
        if hit_tp:
            return {"exit": "target", "exit_idx": k, "exit_price": tp}
        if BE_AT_R is not None and not be and k > q and \
                ((short and l[k] <= entry - BE_AT_R * risk) or (not short and h[k] >= entry + BE_AT_R * risk)):
            stop, be = entry, True
    return {"exit": "open", "exit_idx": len(ltf) - 1, "exit_price": c[-1]}


# ----------------------------------------------------------------------------- chart
def plot_trade(symbol: str, tr: dict, ltf: pd.DataFrame, path: Path) -> None:
    short = tr["signal"] == "short"
    q, k = tr["x_entry_idx"], tr["x_exit_idx"]
    a, b = max(0, tr["x_retest_idx"] - 25), min(len(ltf), k + 25)
    df = ltf.iloc[a:b]
    fig, ax = plt.subplots(figsize=(15, 6.5))
    draw_candles(ax, df)
    x0 = q - a
    xf = max(ltf.index.searchsorted(tr["fvg_time"]) - a, 0)
    ax.add_patch(Rectangle((xf - 0.4, tr["fvg_bottom"]), k - a - xf + 0.4, tr["fvg_top"] - tr["fvg_bottom"],
                           color=BEAR if short else BULL, alpha=0.30, lw=0))
    ax.text(xf, tr["fvg_top"] if short else tr["fvg_bottom"], f" {tr['entry_tf']} entry FVG", fontsize=8,
            va="bottom" if short else "top", color=BEAR if short else BULL)
    ax.hlines(tr["entry_price"], x0, k - a, color="black", lw=1.2)
    ax.hlines(tr["stop"], x0, k - a, color=BEAR, lw=1.4, ls="--")
    ax.hlines(tr["target"], x0, k - a, color=BULL, lw=1.4, ls="--")
    ax.fill_between([x0, k - a], tr["entry_price"], tr["target"], color=BULL, alpha=0.08)
    ax.fill_between([x0, k - a], tr["entry_price"], tr["stop"], color=BEAR, alpha=0.08)
    for y, txt, col in ((tr["entry_price"], f"entry {tr['entry_price']:.2f}", "black"),
                        (tr["stop"], f"stop {tr['stop']:.2f}", BEAR),
                        (tr["target"], f"target {tr['target_level']}", BULL)):
        ax.text(k - a + 1, y, txt, fontsize=8, color=col, va="center", fontweight="bold")
    ax.plot(x0, tr["entry_price"], "v" if short else "^", color=BEAR if short else BULL, ms=12, mec="black")
    ax.plot(k - a, tr["exit_price"], "X", color="black", ms=10)
    ax.set_title(f"{symbol} #{tr['setup']} {tr['signal'].upper()} {tr['entry_tf']} ({tr['entry_mode']} entry) | "
                 f"{tr['entry_time']:%Y-%m-%d %H:%M} -> {tr['exit_time']:%Y-%m-%d %H:%M} | planned {tr['planned_rr']:.2f}R | "
                 f"result {tr['exit'].upper()} {tr['r_net']:+.2f}R (after costs) | stop {STOP_MODE}, {TARGET_R:g}R, BE {BE_AT_R}", fontsize=10)
    _axis(ax, df, tr["entry_tf"])
    ax.set_xlim(-1, len(df) + 12)
    fig.tight_layout()
    fig.savefig(path, dpi=95)
    plt.close(fig)


# ----------------------------------------------------------------------------- main
def _intraday_setups(h1: pd.DataFrame):
    """Rules 1-4 with the intraday liquidity (INTRADAY_LIQ_TFS, 4H swings INTRADAY_4H_PIVOT each side)."""
    import swings
    saved = (ifvg.SWEEP_TFS, dict(swings.PIVOT_BY_TF))
    swings.PIVOT_BY_TF = {**swings.PIVOT_BY_TF, "4H": INTRADAY_4H_PIVOT}
    split = INTRADAY_4H_MODE == "1H FVG" and "4H" in INTRADAY_LIQ_TFS
    ifvg.SWEEP_TFS = tuple(t for t in INTRADAY_LIQ_TFS if t != "4H") if split else INTRADAY_LIQ_TFS
    try:
        h4, setups = build_4h_setups(h1)
        if split:
            import setups_v2
            ifvg.SWEEP_TFS = ("4H",)
            saved_req = setups_v2.REQUIRE_4H_FVG
            setups_v2.REQUIRE_4H_FVG = False
            try:
                _, s2 = setups_v2.build_setups(h1)
            finally:
                setups_v2.REQUIRE_4H_FVG = saved_req
            setups = sorted(setups + s2, key=lambda d: d["signal_time"])
        if INTRADAY_1H_PIVOT > 0:
            import setups_v2
            ifvg.SWEEP_TFS = ("1H",)
            swings.PIVOT_BY_TF = {**swings.PIVOT_BY_TF, "1H": INTRADAY_1H_PIVOT}
            saved_req = setups_v2.REQUIRE_4H_FVG
            setups_v2.REQUIRE_4H_FVG = False
            try:
                _, s3 = setups_v2.build_setups(h1)
            finally:
                setups_v2.REQUIRE_4H_FVG = saved_req
            setups = sorted(setups + s3, key=lambda d: d["signal_time"])
        for ltf, piv in INTRADAY_POI_LAYERS:
            import setups_4hsweep, setups_v2
            ifvg.SWEEP_TFS = (ltf,)
            swings.PIVOT_BY_TF = {**swings.PIVOT_BY_TF, ltf: piv}
            saved_req, saved_f = setups_v2.REQUIRE_4H_FVG, setups_v2.LEVEL_FILTER
            setups_v2.REQUIRE_4H_FVG = False
            setups_v2.LEVEL_FILTER = lambda lv, h, _t=ltf: setups_4hsweep.poi_filter(lv, h, setups_4hsweep.POI_TF[_t])
            try:
                _, s4 = setups_v2.build_setups(h1)
            finally:
                setups_v2.REQUIRE_4H_FVG, setups_v2.LEVEL_FILTER = saved_req, saved_f
            setups = sorted(setups + s4, key=lambda d: d["signal_time"])
        return h4, setups
    finally:
        ifvg.SWEEP_TFS, swings.PIVOT_BY_TF = saved[0], saved[1]


def run() -> pd.DataFrame:
    (OUT / "trades").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "trades").glob("*.png"):
        old.unlink()
    trades, skipped = [], []
    for symbol, (h1_file, m15_file, m5_file) in SYMBOLS.items():
        h1 = load(DATA / h1_file)
        h4, setups = _intraday_setups(h1)
        h1_fvgs = ifvg.find_fvgs(h1)
        ltfs = {"15m": load(DATA / m15_file), "5m": load(DATA / m5_file)}
        ltf_fvgs = {tf: ifvg.find_fvgs(df) for tf, df in ltfs.items()}
        seen_1h = set()
        for n, st in enumerate(setups, 1):
            r5 = find_1h_ifvg(st, h1, h1_fvgs)
            if r5["status"] != "signal":
                continue
            if signal_key(st, r5) in seen_1h:          # same 1H IFVG already traded via another 4H setup
                continue
            seen_1h.add(signal_key(st, r5))
            short = st["signal"] == "short"
            for tf in entry_ltf.selected_tfs():
                ltf = ltfs[tf]                              # fills + exits simulated on the entry timeframe
                for mode in entry_ltf.selected_modes(tf):
                    e = find_entry(st, r5, h1, ltf, ltf_fvgs[tf], mode, ltfs.get(entry_ltf.CLOSE_THROUGH_TF))
                    base = {"symbol": symbol, "setup": n, "signal": st["signal"], "entry_tf": tf, "entry_mode": mode}
                    if e["status"] != "filled":
                        skipped.append({**base, "reason": e["status"]})
                        continue
                    entry, q = e["entry_price"], e["x"]["entry"]
                    if STOP_MODE == "prev_1h_candle":
                        pc = prev_candle(h1, e["entry_time"], pd.Timedelta(hours=1), short, entry, PREV_CANDLE_LOOKBACK)
                        if np.isnan(pc):
                            skipped.append({**base, "reason": "no previous 1H candle beyond entry"})
                            continue
                        sl = pc + SL_BUFFER[symbol] if short else pc - SL_BUFFER[symbol]
                    elif STOP_MODE == "prev_swing":
                        ps = prev_swing(ltf, q, short, entry)
                        if np.isnan(ps):
                            skipped.append({**base, "reason": "no previous swing beyond entry"})
                            continue
                        sl = ps + SL_BUFFER[symbol] if short else ps - SL_BUFFER[symbol]
                    elif STOP_MODE in stops_ext.LTF_KINDS:    # 5m order block; none -> previous 1H candle
                        lv = stops_ext.level_ltf(STOP_MODE, st, r5, h1, h4, ltf, e, entry)
                        if np.isnan(lv):
                            lv = prev_candle(h1, e["entry_time"], pd.Timedelta(hours=1), short, entry, PREV_CANDLE_LOOKBACK)
                        if np.isnan(lv):
                            skipped.append({**base, "reason": "no 5m OB / previous 1H candle beyond entry"})
                            continue
                        sl = lv + SL_BUFFER[symbol] if short else lv - SL_BUFFER[symbol]
                    elif STOP_MODE in stops_ext.KINDS:        # extra stops (stops_ext.py)
                        lv = stops_ext.level(STOP_MODE, st, r5, h1_fvgs, h4, h1, entry)
                        if np.isnan(lv):
                            skipped.append({**base, "reason": f"no {STOP_MODE} level"})
                            continue
                        sl = lv + SL_BUFFER[symbol] if short else lv - SL_BUFFER[symbol]
                    elif STOP_MODE == "4h_extreme":
                        ext = r5["x"]["extreme"]
                        sl = ext + SL_BUFFER[symbol] if short else ext - SL_BUFFER[symbol]
                    else:
                        sl = e["fvg_top"] + SL_BUFFER[symbol] if short else e["fvg_bottom"] - SL_BUFFER[symbol]
                    risk = abs(entry - sl)
                    if (short and sl <= entry) or (not short and sl >= entry):
                        skipped.append({**base, "reason": "stop on wrong side of entry"})
                        continue
                    tp = entry - TARGET_R * risk if short else entry + TARGET_R * risk
                    tp_tag = f"{TARGET_R:g}R {tp:.2f}"
                    sim = simulate(ltf, q, short, entry, sl, tp)
                    pnl = (entry - sim["exit_price"]) if short else (sim["exit_price"] - entry)
                    tr = {**base, "1h_signal_time": r5["h1_signal_time"], "trigger": e["trigger"],
                          "fvg_time": e["fvg_time"], "fvg_bottom": e["fvg_bottom"], "fvg_top": e["fvg_top"],
                          "entry_time": e["entry_time"], "entry_price": entry, "stop": sl, "target": tp,
                          "target_level": tp_tag, "risk_pts": risk, "planned_rr": abs(tp - entry) / risk,
                          "exit": sim["exit"], "exit_time": ltf.index[sim["exit_idx"]], "exit_price": sim["exit_price"],
                          "pnl_pts": pnl, "r_gross": pnl / risk, "r_net": (pnl - COST[symbol]) / risk,
                          "bars_held": sim["exit_idx"] - q,
                          "stop_fallback": (STOP_MODE.startswith("1H OB") or STOP_MODE in stops_ext.LTF_KINDS) and stops_ext.last_fallback,
                          "x_entry_idx": q, "x_exit_idx": sim["exit_idx"], "x_retest_idx": e["x"]["retest"]}
                    trades.append(tr)
                    plot_trade(symbol, tr, ltf, OUT / "trades" / f"{symbol}_{n:02d}_{tf}_{mode}.png")
    t = pd.DataFrame(trades)
    pd.DataFrame(skipped).to_csv(OUT / "not_traded.csv", index=False)
    if not t.empty:
        t[[c for c in t.columns if not c.startswith("x_")]].to_csv(OUT / "trades.csv", index=False)
    else:                                       # don't leave results of an earlier run behind
        for f in ("trades.csv", "summary.csv"):
            (OUT / f).unlink(missing_ok=True)
    return t


def summarise(t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (tf, mode), g in t.groupby(["entry_tf", "entry_mode"]):
        for sym in ["ALL"] + sorted(g["symbol"].unique()):
            s = g if sym == "ALL" else g[g["symbol"] == sym]
            closed = s[s["exit"] != "open"]
            eq = START_BALANCE
            peak, mdd = eq, 0.0
            for r in s.sort_values("entry_time")["r_net"]:
                eq += eq * RISK_PCT / 100 * r
                peak = max(peak, eq)
                mdd = max(mdd, (peak - eq) / peak * 100)
            rows.append({"entry_tf": tf, "entry_mode": mode, "symbol": sym, "trades": len(s),
                         "wins": int((s["exit"] == "target").sum()), "losses": int((s["exit"] == "stop").sum()),
                         "breakeven": int((s["exit"] == "breakeven").sum()),
                         "open": int((s["exit"] == "open").sum()),
                         "win_rate_%": round(100 * (closed["exit"] == "target").mean(), 1) if len(closed) else np.nan,
                         "avg_planned_RR": round(s["planned_rr"].mean(), 2),
                         "gross_win_R": round(s.loc[s["r_net"] > 0, "r_net"].sum(), 2),
                         "gross_loss_R": round(abs(s.loc[s["r_net"] < 0, "r_net"].sum()), 2),
                         # profit factor = gross profit / gross loss (inf = no losing trades)
                         "profit_factor": (round(s.loc[s["r_net"] > 0, "r_net"].sum() / -s.loc[s["r_net"] < 0, "r_net"].sum(), 2)
                                           if (s["r_net"] < 0).any() else float("inf")),
                         "total_R": round(s["r_net"].sum(), 2), "avg_R": round(s["r_net"].mean(), 2),
                         "avg_hold_days": round(((s["exit_time"] - s["entry_time"]).dt.total_seconds() / 86400).mean(), 1),
                         "median_hold_days": round(((s["exit_time"] - s["entry_time"]).dt.total_seconds() / 86400).median(), 1),
                         f"end_balance_{RISK_PCT:g}%": round(eq, 2), "max_dd_%": round(mdd, 2)})
    return pd.DataFrame(rows)


def main() -> None:
    t = run()
    if t.empty:
        print("No trades.")
        return
    pd.set_option("display.width", 250)
    show = t.copy()
    for c in ("entry_time", "exit_time"):
        show[c] = show[c].dt.strftime("%m-%d %H:%M")
    print(show[["symbol", "setup", "signal", "entry_tf", "entry_mode", "entry_time", "entry_price", "stop", "target",
                "target_level", "planned_rr", "exit", "exit_time", "r_net"]].round(2).to_string(index=False))
    s = summarise(t)
    s.to_csv(OUT / "summary.csv", index=False)
    print("\nSUMMARY (R after costs; equity example: "
          f"${START_BALANCE:,} start, {RISK_PCT:g}% risk per trade, compounding)")
    print(s.to_string(index=False))
    print("\nNot traded:", pd.read_csv(OUT / "not_traded.csv")["reason"].value_counts().to_dict())


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    entry_ltf.add_entry_arg(ap)
    entry_ltf.apply_entry_arg(ap.parse_args())
    print("entry filter:", ", ".join(f"{t} {m}" for t, m in entry_ltf.selected_entries()))
    main()
