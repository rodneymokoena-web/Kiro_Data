"""Rule 5: retest of the 4H IFVG -> 1H FVGs formed during the retest -> 1H FVG inverted with displacement.

Usage:
    .venv/bin/python ifvg_1h.py

Pipeline per 4H setup (rules 1-4, see ote.py / structure.py):
    SHORT (mirror for LONG):
    1. RETEST     Within RETEST_WINDOW after the 4H signal, a 1H high reaches the 4H IFVG bottom.
                  Cancelled first if price trades above the 4H sweep extreme.
    2. 1H FVGs    Bullish 1H FVGs formed by the retest leg: from the lowest low since the sweep extreme
                  up to the 1H inversion. They must still be intact (not closed below) at the retest.
    3. INVERSION  After the retest, a 1H candle CLOSES below one of those bullish 1H FVGs,
                  within INVERT_WINDOW_1H candles of the retest.
    4. DISPLACEMENT  The inversion candle ends a run of >= 2 consecutive bearish 1H candles moving
                  >= 1 x ATR(14) on 1H (same test as the 4H rule, structure.displacement).
                  If the first inversion is weak, the next qualifying one is used.
    -> 1H SIGNAL at the close of that 1H inversion candle.

Outputs:
    output/ifvg_1h/{SYMBOL}_1h_signals.csv
    output/ifvg_1h/setups/{SYMBOL}_{n}_{date}_{dir}.png    4H setup | 1H retest + 1H IFVG
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

import ifvg
import structure
from ote import BEAR, BULL, H4, _axis, draw_4h_panel
from swings import DATA, SYMBOLS, add_break_times, build_htf, draw_candles, find_swings, load

# ----------------------------------------------------------------------------- CONFIG
RETEST_WINDOW = pd.Timedelta(hours=48)   # 4H IFVG must be retested within this time after the 4H signal
# Rule 4 cancellation: True = the setup dies if price trades beyond the sweep extreme before the retest / 1H IFVG.
# False = no cancellation: retests after such a break still count, and the sweep extreme moves with price (highest high
#         from the sweep extreme to the 1H IFVG signal candle, for a short) - it is the swing stop / invalidation level.
RETEST_CANCEL = True
INTRADAY_SWEEP = __import__("os").environ.get("INTRADAY_SWEEP", "5m")   # "4h" = a 4H wick through the level (current) | "5m" = 5m sweep definition (swings.add_break_times_5m)
FVG_LIQ_1H = __import__("os").environ.get("FVG_LIQ_1H", "1") == "1"   # intraday: fresh 1H FVG far edges as Rule 1 liquidity too
INVERT_WINDOW_1H = 20                    # 1H candles after the retest for the 1H FVG to be inverted

OUT = Path(__file__).parent / "output" / "ifvg_1h"


# ----------------------------------------------------------------------------- setups (rules 1-4)
# "v2" = revised rules 1-3 (setups_v2.py: D equal H/L sweep -> 4H FVG in leg -> 1H FVG inverted with displacement
#        + MSS). "v3" = revised rule 3 (setups_v3.py: rule 2 4H FVG inverted by a 1H close, 1H displacement + MSS,
#        4H CISD; then the v1 rules 4-5). "v1" = previous rules 2-5 (4H IFVG + CISD/MSS -> 4H IFVG retest -> 1H IFVG).
PIPELINE = "v1"


def build_4h_setups(h1: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    if PIPELINE == "v2":
        import setups_v2
        return setups_v2.build_setups(h1)
    if PIPELINE == "v3":                   # revised rule 3: 4H FVG inverted by a 1H close (setups_v3.py)
        import setups_v3
        return setups_v3.build_setups(h1)
    return build_4h_setups_v1(h1)


# Rule 3 confirmation of the 4H inversion (v1 pipeline):
#   "1H MSS"      = (default, rule 3 "M1") 4H displacement AND a 1H MSS - no 4H CISD at all: a 1H close through the
#                   previous 1H swing low (short) by the close of the 4H inversion candle; MSS_MODE_1H "ext" = the 1H
#                   swing before the sweep extreme, "any" = most recent 1H swing, before or after the sweep (structure.mss)
#   "CISD or MSS" = previous rule: 4H displacement AND (4H CISD or 4H MSS)
CONFIRM_4H = "1H MSS"
MSS_MODE_1H = "ext"
MSS_REQUIRED_4H = True     # False = the 4H inversion needs only 4H displacement (no 1H MSS)


def _accept_1h_mss(h1: pd.DataFrame, h4_full: pd.DataFrame):
    idx1 = h1.index

    def accept(h4: pd.DataFrame, fvg, s: int, fvg_dir: str) -> dict:
        short = fvg_dir == "bull"
        j = int(fvg["inv_idx"])
        ok_d, run_len, move, _ = structure.displacement(h4, j, short)
        s1 = idx1.searchsorted(h4.index[s])                              # first 1H candle of the 4H sweep candle
        j1 = idx1.searchsorted(h4_full["End"].iat[j]) - 1                # last 1H candle of the 4H inversion candle
        ok_m, lv, t = structure.mss(h1, s1, j1, short, MSS_MODE_1H) if j1 >= s1 else (False, np.nan, -1)
        atr_j = structure._arrays(h4)[4][j]
        ok_m = ok_m or not MSS_REQUIRED_4H
        return {"passed": bool(ok_d and ok_m), "confirm": "MSS1H" if ok_m else "-",
                "disp_candles": int(run_len), "disp_atr": round(float(move / atr_j), 2), "mss_level": lv,
                "reject_reason": "" if ok_d and ok_m else ("no displacement" if not ok_d else "no 1H MSS")}
    return accept


def build_4h_setups_v1(h1: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    htf = {tf: build_htf(h1, tf) for tf in ("D", "W", "M", "4H")}
    f1 = h1.assign(Start=h1.index, End=h1.index + pd.Timedelta(hours=1))
    htf["1H"] = f1
    import swings as _S
    def _lv(tf):
        if tf == "4H" and ifvg.SIG_4H:
            return _S.significant_4h_levels(h1)
        if tf == "1H":                      # 1H liquidity swings use the 4H size (10); the session filter keeps its own 1H size
            saved = _S.PIVOT_BY_TF.get("1H")
            _S.PIVOT_BY_TF["1H"] = ifvg.RULE1_4H_PIVOT
            try:
                return find_swings(htf[tf], tf)
            finally:
                if saved is None:
                    _S.PIVOT_BY_TF.pop("1H", None)
                else:
                    _S.PIVOT_BY_TF["1H"] = saved
        return find_swings(htf[tf], tf)
    _parts = [_lv(tf) for tf in ifvg.SWEEP_TFS]       # rule 1 liquidity
    if ifvg.SESSION_TFS:
        _parts.append(_S.session_levels(h1, ifvg.SESSION_TFS))
    if ifvg.FVG_LIQ:
        _parts.append(_S.fvg_far_edge_levels(htf["4H"]))
    if ifvg.FVG_LIQ and FVG_LIQ_1H:
        _parts.append(_S.fvg_far_edge_levels(f1, "1HFVG"))        # fresh 1H FVG far edges (intraday)
    levels = pd.concat(_parts, ignore_index=True)
    h4_full = htf["4H"]
    h4 = h4_full.drop(columns=["Start", "End"])
    accept = structure.quality if CONFIRM_4H == "CISD or MSS" else _accept_1h_mss(h1, h4_full)
    if INTRADAY_SWEEP == "5m":                # sweep judged on 5m candles (swings.add_break_times_5m)
        m5 = _S.load(_S.DATA / _S.SYMBOLS[list(_S.SYMBOLS)[0]][2])
        lv_b = _S.add_break_times_5m(levels, m5, pd.DatetimeIndex(h4.index))
    else:
        lv_b = add_break_times(levels, h4)
    setups = ifvg.find_setups(h4, lv_b, "4H", accept=accept)
    out = []
    for st in setups.to_dict("records"):
        j = st["x_inv_idx"]
        st["signal_time"] = h4_full["End"].iat[j]
        seg = h4.iloc[st["x_sweep_idx"]:j + 1]
        st["extreme_time"] = seg["High"].idxmax() if st["signal"] == "short" else seg["Low"].idxmin()
        out.append(st)
    return h4, out


# ----------------------------------------------------------------------------- rule 5
def signal_key(st: dict, r5: dict) -> tuple:
    """Identity of a 1H IFVG signal: two 4H setups that lead to the same 1H IFVG must be traded only once."""
    return (st["signal"], r5["h1_signal_time"], round(float(r5["h1_fvg_bottom"]), 6), round(float(r5["h1_fvg_top"]), 6))


def find_1h_ifvg(st: dict, h1: pd.DataFrame, fvgs: pd.DataFrame) -> dict:
    if "r5" in st:                         # v2 pipeline: the 1H IFVG signal is part of the setup (rule 3)
        return st["r5"]
    return find_1h_ifvg_v1(st, h1, fvgs)


def find_1h_ifvg_v1(st: dict, h1: pd.DataFrame, fvgs: pd.DataFrame) -> dict:
    short = st["signal"] == "short"
    o, h, l, c = (h1[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx, n = h1.index, len(h1)
    res = {"status": "no data", "retest_time": pd.NaT, "h1_fvg_time": pd.NaT, "h1_fvg_bottom": np.nan,
           "h1_fvg_top": np.nan, "h1_signal_time": pd.NaT, "h1_signal_close": np.nan,
           "h1_disp_candles": 0, "h1_disp_atr": np.nan, "x": {}}

    a0, a1 = idx.searchsorted(st["extreme_time"]), idx.searchsorted(st["extreme_time"] + st.get("extreme_span", H4))
    s0, end = idx.searchsorted(st["signal_time"]), min(idx.searchsorted(st["signal_time"] + RETEST_WINDOW), n)
    if a1 <= a0 or s0 >= n:
        return res
    anchor = a0 + int(np.argmax(h[a0:a1]) if short else np.argmin(l[a0:a1]))
    extreme = h[anchor] if short else l[anchor]
    edge = st["fvg_bottom"] if short else st["fvg_top"]

    # first bar after the signal that trades beyond the sweep extreme = invalidation
    beyond = np.where(h[s0:] > extreme)[0] if short else np.where(l[s0:] < extreme)[0]
    inval = s0 + int(beyond[0]) if len(beyond) else n
    if not RETEST_CANCEL:
        inval = n
    res["x"] = {"anchor": anchor, "extreme": extreme, "inval": inval}

    # 1. every 1H bar that touches the 4H IFVG (before invalidation) is a possible retest.
    #    Consecutive touching bars belong to the same retest; each retest has its own leg.
    stop = min(end, inval)
    touch = (np.where(h[s0:stop] >= edge)[0] if short else np.where(l[s0:stop] <= edge)[0]) + s0
    if not len(touch):
        res["status"] = "invalidated" if inval < end else "no retest"
        return res
    retests = [int(t) for k, t in enumerate(touch) if k == 0 or t != touch[k - 1] + 1]
    res.update(status="no 1H IFVG", retest_time=idx[retests[0]])
    res["x"].update(retest=retests[0], n_retests=len(retests))
    want = "bull" if short else "bear"
    n_cand = 0
    for r in retests:
        # 2. 1H FVGs of this retest leg: leg starts at the lowest low (short) since the sweep extreme
        origin = anchor + int(np.argmin(l[anchor:r + 1]) if short else np.argmax(h[anchor:r + 1]))
        last = min(r + INVERT_WINDOW_1H, inval - 1, n - 1)
        cand = fvgs[(fvgs["dir"] == want) & (fvgs["idx"] - 2 >= origin) & (fvgs["inv_idx"] >= r)
                    & (fvgs["inv_idx"] <= last) & (fvgs["inv_idx"] > fvgs["idx"])]
        n_cand += len(cand)
        # 3+4. first inversion after this retest with >= 2-candle displacement
        cand = cand.sort_values(["inv_idx", "bottom" if short else "top"], ascending=[True, short])
        for f in cand.itertuples(index=False):
            ok, run_len, move, run_start = structure.displacement(h1, int(f.inv_idx), short)
            if ok:
                j = int(f.inv_idx)
                res.update(status="signal", retest_time=idx[r], h1_fvg_time=idx[int(f.idx) - 2],
                           h1_fvg_bottom=f.bottom, h1_fvg_top=f.top,
                           h1_signal_time=idx[j] + pd.Timedelta(hours=1), h1_signal_close=c[j],
                           h1_disp_candles=run_len, h1_disp_atr=round(move / structure._arrays(h1)[4][j], 2))
                res["x"].update(retest=r, origin=origin, fvg_idx=int(f.idx), inv_idx=j, disp_start=run_start,
                                n_candidates=n_cand)
                if not RETEST_CANCEL:          # extreme follows price up to the 1H IFVG signal
                    a2 = anchor + int(np.argmax(h[anchor:j + 1]) if short else np.argmin(l[anchor:j + 1]))
                    res["x"].update(anchor_new=a2, extreme=h[a2] if short else l[a2], extreme_moved=a2 != anchor)
                return res
    res["x"]["n_candidates"] = n_cand
    return res


# ----------------------------------------------------------------------------- chart
def plot(symbol: str, n: int, st: dict, h4: pd.DataFrame, h1: pd.DataFrame, r5: dict, path: Path) -> None:
    short = st["signal"] == "short"
    zc, fc = (BEAR, BULL) if short else (BULL, BEAR)
    fig, (ax4, ax1) = plt.subplots(1, 2, figsize=(19, 7), gridspec_kw={"width_ratios": [1, 1.25]})
    draw_4h_panel(ax4, st, h4)

    x = r5["x"]
    s0 = h1.index.searchsorted(st["signal_time"])
    a = max(0, x["anchor"] - 15)
    stop = x.get("inv_idx", x.get("retest", s0 + 24))
    b = min(len(h1), stop + 20)
    df = h1.iloc[a:b]
    draw_candles(ax1, df)
    xs = s0 - a
    ax1.axvline(xs, color="gray", lw=0.8, ls=":")
    ax1.add_patch(Rectangle((xs, st["fvg_bottom"]), len(df) - xs, st["fvg_top"] - st["fvg_bottom"],
                            facecolor=zc, alpha=0.22, hatch="///", edgecolor=zc, lw=0.6))
    ax1.text(len(df) - 1, st["fvg_top"] if short else st["fvg_bottom"], "4H IFVG", fontsize=8, color=zc,
             ha="right", va="bottom" if short else "top", fontweight="bold")
    ax1.hlines(x["extreme"], x["anchor"] - a, len(df), color="black", lw=0.8, ls=":")
    ax1.text(len(df) - 1, x["extreme"], "invalidation", fontsize=7, ha="right", va="bottom")
    if "retest" in x:
        rr = x["retest"] - a
        ax1.plot(rr, h1["High"].iat[x["retest"]] if short else h1["Low"].iat[x["retest"]], "o", ms=9,
                 mfc="none", mec="black", mew=1.5)
        ax1.annotate("retest", (rr, h1["High"].iat[x["retest"]] if short else h1["Low"].iat[x["retest"]]),
                     xytext=(0, 10 if short else -14), textcoords="offset points", ha="center", fontsize=8)
    if "origin" in x and "retest" in x:
        ax1.axvspan(x["origin"] - a - 0.5, x["retest"] - a + 0.5, color="gray", alpha=0.07)
    if r5["status"] == "signal":
        i1, j = x["fvg_idx"] - 2 - a, x["inv_idx"] - a
        ax1.add_patch(Rectangle((i1 - 0.4, r5["h1_fvg_bottom"]), j - i1 + 0.4, r5["h1_fvg_top"] - r5["h1_fvg_bottom"],
                                color=fc, alpha=0.35, lw=0))
        ax1.add_patch(Rectangle((j - 0.4, r5["h1_fvg_bottom"]), min(15, len(df) - j), r5["h1_fvg_top"] - r5["h1_fvg_bottom"],
                                facecolor=zc, alpha=0.55, hatch="xx", edgecolor=zc, lw=0.8))
        ax1.text(j + 0.6, r5["h1_fvg_bottom"] if short else r5["h1_fvg_top"], "1H IFVG", fontsize=8, color=zc,
                 va="top" if short else "bottom", fontweight="bold")
        ax1.axvspan(x["disp_start"] - a - 0.5, j + 0.5, color=zc, alpha=0.10)
        y = h1["High"].iat[x["inv_idx"]] if short else h1["Low"].iat[x["inv_idx"]]
        ax1.plot(j, y, "v" if short else "^", color=zc, ms=13, mec="black")
        msg = (f"1H IFVG {r5['h1_fvg_bottom']:.2f}-{r5['h1_fvg_top']:.2f} inverted, displacement "
               f"{r5['h1_disp_candles']}c / {r5['h1_disp_atr']} ATR -> {st['signal'].upper()} @ "
               f"{r5['h1_signal_time']:%m-%d %H:%M} close {r5['h1_signal_close']:.2f}")
    else:
        msg = r5["status"].upper()
    ax1.set_title(f"1H | {msg}", fontsize=9)
    _axis(ax1, df, "1H")
    fig.suptitle(f"{symbol} setup #{n} ({st['signal']}) | grey band = retest leg | dotted = 4H signal close | "
                 f"hatched / = 4H IFVG | hatched x = 1H IFVG", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=95)
    plt.close(fig)


# ----------------------------------------------------------------------------- main
def main() -> None:
    (OUT / "setups").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "setups").glob("*.png"):
        old.unlink()
    for symbol, (h1_file, _, _) in SYMBOLS.items():
        h1 = load(DATA / h1_file)
        h4, setups = build_4h_setups(h1)
        fvgs = ifvg.find_fvgs(h1)
        rows = []
        for n, st in enumerate(setups, 1):
            r5 = find_1h_ifvg(st, h1, fvgs)
            rows.append({"setup": n, "signal": st["signal"], "4h_signal_time": st["signal_time"],
                         "swept_levels": st["swept_levels"], "4h_ifvg_bottom": st["fvg_bottom"],
                         "4h_ifvg_top": st["fvg_top"], "4h_confirm": st["confirm"],
                         **{k: v for k, v in r5.items() if k != "x"},
                         "candidate_1h_fvgs": r5["x"].get("n_candidates", 0)})
            plot(symbol, n, st, h4, h1, r5,
                 OUT / "setups" / f"{symbol}_{n:02d}_{st['signal_time']:%Y%m%d_%H%M}_{st['signal']}.png")
        res = pd.DataFrame(rows)
        res.to_csv(OUT / f"{symbol}_1h_signals.csv", index=False)
        print(f"\n{symbol}: {len(setups)} 4H setups -> {int((res.status == 'signal').sum())} 1H IFVG signals")
        print("  outcome:", res["status"].value_counts().to_dict())
        sig = res[res.status == "signal"]
        if len(sig):
            hrs = (sig["h1_signal_time"] - sig["4h_signal_time"]).dt.total_seconds() / 3600
            print(f"  1H signal comes {hrs.median():.0f}h (median) after the 4H signal; "
                  f"1H displacement median {sig['h1_disp_candles'].median():.0f} candles / {sig['h1_disp_atr'].median():.2f} ATR")


if __name__ == "__main__":
    main()
