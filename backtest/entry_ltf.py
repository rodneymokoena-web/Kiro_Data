"""Rule 6: 1H IFVG retest -> 1H CISD or 15m/5m MSS (with displacement) -> entry at the MSS FVG (touch / 50% CE).

Usage:
    .venv/bin/python entry_ltf.py                            # all four entries (compare)
    .venv/bin/python entry_ltf.py --entry 15m-touch          # only 15m touch entries
    .venv/bin/python entry_ltf.py --entry 15m-ce 5m-touch    # any combination
    choices: 15m-touch, 15m-ce, 5m-touch, 5m-ce, all   (or set ENTRY_FILTER below)

Starts from the 1H IFVG signals of rule 5 (ifvg_1h.py). For each entry timeframe (15m, 5m) separately.
SHORT described; LONG is the mirror image.
    1. RETEST     Within RETEST_WINDOW_1H after the 1H signal, price touches the 1H IFVG
                  (high >= 1H IFVG bottom). Every separate touch is a candidate retest.
    2. TRIGGER    Within TRIGGER_WINDOW after the touch, the FIRST of:
                    a) 1H CISD: a 1H candle closes below the OPEN of the first bullish candle of the run that
                       delivered price into the retest high, with 1H displacement (>= 2 candles, >= 1 ATR)
                    b) LTF MSS: an entry-TF candle closes below the last confirmed entry-TF swing low
                       (LTF_PIVOT each side) of the retest leg, with entry-TF displacement
    3. ENTRY FVG  Bearish entry-TF FVG formed in the leg from the retest high down through the trigger
                  candle - the breaking candle is usually candle 2 of the FVG, so it may complete up to
                  FVG_AFTER_TRIGGER candles after the trigger. The one centred on the break is preferred.
                  Orders are only live after the FVG is confirmed (close of its 3rd candle).
    4. ENTRY      Limit order at the FVG near edge ("touch" = FVG bottom) or 50% CE (midpoint).
                  Causal: before each candle the order uses the best FVG that has already completed, and
                  moves to a better one if it completes before the fill (no look-ahead).
                  Cancelled if a candle OPENS beyond the retest high (gap), or after FILL_WINDOW. A candle
                  that trades through the entry and on to the retest high fills and is then stopped out.
                  (LEGACY_FILLS = True restores the old, slightly optimistic behaviour.)
    CLOSE-BACK-THROUGH (CANCEL_ON_CLOSE_THROUGH) - entry FVG only, NOT the 1H IFVG:
                  once the 15m/5m MSS FVG has formed, a 5m candle (CLOSE_THROUGH_TF) that closes back
                  through it (below its bottom for longs, above its top for shorts) cancels the entry
                  order - unless the very next 5m candle re-inverts it (closes back beyond the other side).
                  Then the order is live again; it cannot fill during that candle.
    Hard invalidation throughout: price beyond the 4H sweep extreme.

Outputs:
    output/entry/{SYMBOL}_entries.csv
    output/entry/setups/{SYMBOL}_{n}_{date}_{dir}.png     1H | 15m | 5m
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

import ifvg
import ote
import structure
from ifvg_1h import build_4h_setups, find_1h_ifvg
from ote import BEAR, BULL, _axis
from swings import DATA, SYMBOLS, draw_candles, load

# ----------------------------------------------------------------------------- CONFIG
ENTRY_FILTER = ["5m touch"]       # entry filter: any of "15m touch", "15m ce", "5m touch", "5m ce" | "all"
RETEST_WINDOW_1H = pd.Timedelta(hours=24)   # 1H IFVG must be retested within this time after the 1H signal
TRIGGER_WINDOW = pd.Timedelta(hours=12)     # 1H CISD / LTF MSS must occur within this time after the touch
FILL_WINDOW = pd.Timedelta(hours=12)        # entry limit valid this long after the trigger
ENTRY_TFS = ["15m", "5m"]
FVG_AFTER_TRIGGER = 2                       # entry FVG may complete up to N candles after the trigger candle
LEGACY_FILLS = False                        # True = old fill logic (1-candle look-ahead, optimistic cancel)
CANCEL_ON_CLOSE_THROUGH = True              # a close back through the ENTRY (MSS) FVG cancels the entry order ...
CLOSE_THROUGH_TF = "5m"                     # ... checked on this timeframe's closes ("5m"; "1m" needs 1m data)
REINVERT_BARS = 1                           # ... unless re-inverted within this many CLOSE_THROUGH_TF candles
                                            # (not applied to the 1H IFVG)

OUT = Path(__file__).parent / "output" / "entry"
H1 = pd.Timedelta(hours=1)
NEVER = pd.Timestamp.max.tz_localize("UTC")


ALL_ENTRIES = [("15m", "touch"), ("15m", "ce"), ("5m", "touch"), ("5m", "ce")]


def selected_entries() -> list[tuple[str, str]]:
    """(entry timeframe, entry type) pairs enabled by ENTRY_FILTER, in a fixed order."""
    want = {tuple(e.replace("-", " ").lower().split()) for e in ENTRY_FILTER}
    if ("all",) in want:
        return list(ALL_ENTRIES)
    bad = want - set(ALL_ENTRIES)
    if bad:
        raise ValueError(f"unknown entry filter {sorted(' '.join(b) for b in bad)}; "
                         f"use {[' '.join(e) for e in ALL_ENTRIES]} or 'all'")
    return [e for e in ALL_ENTRIES if e in want]


def selected_modes(tf: str) -> list[str]:
    return [m for t, m in selected_entries() if t == tf]


def selected_tfs() -> list[str]:
    return [tf for tf in ENTRY_TFS if selected_modes(tf)]


def add_entry_arg(ap) -> None:
    choices = ["all"] + [f"{t}-{m}" for t, m in ALL_ENTRIES]
    ap.add_argument("--entry", nargs="+", choices=choices, default=None,
                    help="entries to test, e.g. --entry 15m-touch 5m-ce (default: ENTRY_FILTER)")


def apply_entry_arg(args) -> None:
    global ENTRY_FILTER
    if args.entry:
        ENTRY_FILTER = list(args.entry)


# ----------------------------------------------------------------------------- close-back-through rule
def zone_state(ct: pd.DataFrame, bot: float, top: float, short: bool, t_start: pd.Timestamp,
               t_end: pd.Timestamp) -> tuple[pd.Timestamp, list]:
    """On the CLOSE_THROUGH_TF candles `ct` from t_start: time the zone [bot, top] is closed back through
    (cancel, NEVER if not), and the suspended intervals where it was closed through but re-inverted
    by the next REINVERT_BARS candles. LONG: close below bot = through, close above top = re-inverted."""
    if not CANCEL_ON_CLOSE_THROUGH or ct is None:
        return NEVER, []
    c, idx, n = ct["Close"].to_numpy(), ct.index, len(ct)
    bar = idx[1] - idx[0]
    k, k1 = idx.searchsorted(t_start), min(idx.searchsorted(t_end), n)
    susp = []
    while k < k1:
        if (short and c[k] > top) or (not short and c[k] < bot):          # closed back through
            back = [m for m in range(k + 1, min(k + 1 + REINVERT_BARS, n))
                    if (short and c[m] < bot) or (not short and c[m] > top)]
            if back:                                                        # re-inverted immediately
                susp.append((idx[k] + bar, idx[back[0]] + bar))
                k = back[0] + 1
                continue
            return idx[k] + bar, susp
        k += 1
    return NEVER, susp


def _blocked(t: pd.Timestamp, susp: list) -> bool:
    return any(a <= t < b for a, b in susp)


# ----------------------------------------------------------------------------- triggers
def h1_cisd(h1: pd.DataFrame, short: bool, t_touch: pd.Timestamp, t_end: pd.Timestamp, susp: list = ()) -> tuple:
    """First 1H CISD with displacement after the touch. Returns (close_time, level) or (NaT, nan)."""
    o, h, l, c = (h1[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
    idx = h1.index
    q0 = idx.searchsorted(t_touch.floor("h"))
    q1 = idx.searchsorted(t_end)
    if q0 >= len(h1):
        return pd.NaT, np.nan
    e = q0
    for q in range(q0, min(q1, len(h1))):
        if (short and h[q] > h[e]) or (not short and l[q] < l[e]):
            e = q
            continue
        # delivery run into the extreme: consecutive bullish (short) candles ending at e (or e-1)
        bull = lambda i: c[i] > o[i] if short else c[i] < o[i]
        d = e if bull(e) else e - 1
        m = d
        while m >= 0 and bull(m):
            m -= 1
        if d < 0 or m >= d:
            continue
        lvl = o[m + 1]
        if ((short and c[q] < lvl) or (not short and c[q] > lvl)) and structure.displacement(h1, q, short)[0] \
                and not _blocked(idx[q] + H1, susp):
            return idx[q] + H1, lvl
    return pd.NaT, np.nan


def find_entry(st: dict, r5: dict, h1: pd.DataFrame, ltf: pd.DataFrame, fvgs: pd.DataFrame, mode: str,
               ct: pd.DataFrame | None = None) -> dict:
    """ct = CLOSE_THROUGH_TF candles used for the close-back-through rule."""
    short = st["signal"] == "short"
    res = {"status": "no 1H signal", "retest_time": pd.NaT, "trigger": "", "trigger_time": pd.NaT,
           "trigger_level": np.nan, "fvg_time": pd.NaT, "fvg_bottom": np.nan, "fvg_top": np.nan,
           "entry_price": np.nan, "entry_time": pd.NaT, "retest_extreme": np.nan,
           "cancel_time": pd.NaT, "reinversions": 0, "x": {}}
    if r5["status"] != "signal":
        return res
    idx, n = ltf.index, len(ltf)
    sig_t = r5["h1_signal_time"]
    if idx[0] > sig_t - H1 or idx[-1] < sig_t:
        res["status"] = "no data"
        return res
    o, h, l, c, ph, pl = ote._ltf_arrays(ltf)
    bar = idx[1] - idx[0]
    edge = r5["h1_fvg_bottom"] if short else r5["h1_fvg_top"]
    extreme = r5["x"]["extreme"]
    s_pre, s0 = idx.searchsorted(sig_t - H1), idx.searchsorted(sig_t)
    end = min(idx.searchsorted(sig_t + RETEST_WINDOW_1H), n)
    beyond = np.where(h[s0:] > extreme)[0] if short else np.where(l[s0:] < extreme)[0]
    inval = s0 + int(beyond[0]) if len(beyond) else n
    # the close-back-through rule is NOT applied to the 1H IFVG (only to the entry FVG, below)
    cancel_t, susp, cancel_i = NEVER, [], n
    stop_i = inval                                                  # first bar the setup is no longer valid

    touch = (np.where(h[s0:min(end, stop_i)] >= edge)[0] if short else np.where(l[s0:min(end, stop_i)] <= edge)[0]) + s0
    touch = np.array([t for t in touch if not _blocked(idx[t], susp)], dtype=int)
    if not len(touch):
        res["status"] = "invalidated" if inval < end else "no retest"
        return res
    retests = [int(t) for k, t in enumerate(touch) if k == 0 or t != touch[k - 1] + 1]
    res.update(status="no trigger", retest_time=idx[retests[0]])
    piv = pl if short else ph
    for r in retests:
        origin = s_pre + int(np.argmin(l[s_pre:r + 1]) if short else np.argmax(h[s_pre:r + 1]))
        tend = min(idx.searchsorted(idx[r] + TRIGGER_WINDOW), stop_i, n)
        # (b) MSS on the entry timeframe
        rh, mss_i, mss_lvl = r, None, np.nan
        for p in range(r, tend):
            if (short and h[p] > h[rh]) or (not short and l[p] < l[rh]):
                rh = p
                continue
            cand = piv[(piv >= origin) & (piv < rh) & (piv + ote.LTF_PIVOT < p)]
            if not len(cand):
                continue
            lvl = l[cand[-1]] if short else h[cand[-1]]
            if ((short and c[p] < lvl) or (not short and c[p] > lvl)) and structure.displacement(ltf, p, short)[0] \
                    and not _blocked(idx[p] + bar, susp):
                mss_i, mss_lvl = p, lvl
                break
        mss_t = idx[mss_i] + bar if mss_i is not None else pd.NaT
        # (a) CISD on 1H
        cisd_t, cisd_lvl = h1_cisd(h1, short, idx[r], idx[tend - 1] + bar if tend > r else idx[r], susp)
        if pd.notna(cisd_t) and cisd_t > cancel_t:
            cisd_t = pd.NaT
        options = [(t, k, v) for t, k, v in ((mss_t, "MSS", mss_lvl), (cisd_t, "1H CISD", cisd_lvl)) if pd.notna(t)]
        if not options:
            continue
        trig_t, trig, trig_lvl = min(options, key=lambda x: x[0])
        trig_i = idx.searchsorted(trig_t) - 1                       # last entry-TF bar inside the trigger candle
        hi_i = r + int(np.argmax(h[r:trig_i + 1]) if short else np.argmin(l[r:trig_i + 1]))   # retest extreme
        res.update(status="trigger, no FVG", retest_time=idx[r], trigger=trig, trigger_time=trig_t,
                   trigger_level=trig_lvl, retest_extreme=h[hi_i] if short else l[hi_i])
        res["x"].update({"retest": r, "origin": origin, "hi": hi_i, "trig": trig_i, "mss": mss_i})
        # entry FVG formed in the leg from the retest extreme through the trigger
        want = "bear" if short else "bull"
        # the breaking candle is usually candle 2 of the FVG -> allow the FVG to complete shortly after
        fv = fvgs[(fvgs["dir"] == want) & (fvgs["idx"] - 2 >= hi_i) & (fvgs["idx"] <= trig_i + FVG_AFTER_TRIGGER)]
        if fv.empty:
            return res
        fv = fv.assign(dist=(fv["idx"] - 1 - trig_i).abs()).sort_values("idx")
        fend = min(idx.searchsorted(trig_t + FILL_WINDOW), n)
        _ct_cache: dict[int, tuple] = {}

        def use_fvg(f) -> tuple:
            """Order level + close-back-through state for one candidate FVG (cached)."""
            k3 = int(f["idx"])
            if k3 not in _ct_cache:
                lvl = (f["bottom"] if short else f["top"]) if mode == "touch" else (f["bottom"] + f["top"]) / 2
                c_t, sp = zone_state(ct, f["bottom"], f["top"], short, idx[k3] + bar, trig_t + FILL_WINDOW)
                _ct_cache[k3] = (lvl, c_t, idx.searchsorted(c_t) if c_t < NEVER else n, sp)
            return _ct_cache[k3]

        def record(f) -> None:
            lvl, c_t, _, sp = use_fvg(f)
            res.update(fvg_time=idx[int(f["idx"]) - 2], fvg_bottom=f["bottom"], fvg_top=f["top"],
                       cancel_time=c_t if c_t < NEVER else pd.NaT, reinversions=len(sp))
            res["x"].update(fvg=int(f["idx"]), susp=sp)

        if LEGACY_FILLS:
            # previous behaviour (kept for comparison): FVG chosen with 1 candle of look-ahead,
            # order cancelled if the candle trades beyond the retest extreme even when it also hit the entry
            f = fv.iloc[fv["dist"].argsort(kind="stable").iloc[0]]
            record(f)
            res["status"] = "expired"
            level, _, cancel_i, susp = use_fvg(f)
            for q in range(max(trig_i, int(f["idx"])) + 1, fend):
                if q >= cancel_i:
                    res["status"] = "cancelled (5m close back through entry FVG)"
                    break
                if (short and h[q] > h[hi_i]) or (not short and l[q] < l[hi_i]):
                    res["status"] = "cancelled"
                    break
                if _blocked(idx[q], susp):
                    continue
                if (short and h[q] >= level) or (not short and l[q] <= level):
                    res.update(status="filled", entry_price=max(level, o[q]) if short else min(level, o[q]),
                               entry_time=idx[q])
                    res["x"]["entry"] = q
                    break
            return res

        # causal: before each candle q, use the best FVG that has COMPLETED by q-1
        # (closest to the trigger, earliest on ties); the order may move to a better FVG until it fills
        res["status"] = "expired"
        for q in range(trig_i + 1, fend):
            known = fv[fv["idx"] <= q - 1]
            if known.empty:
                continue
            f = known.iloc[known["dist"].argsort(kind="stable").iloc[0]]
            record(f)
            level, _, cancel_i, susp = use_fvg(f)
            if q >= cancel_i:
                res["status"] = "cancelled (5m close back through entry FVG)"
                break
            if (short and o[q] > h[hi_i]) or (not short and o[q] < l[hi_i]):
                res["status"] = "cancelled (gap beyond retest extreme)"
                break
            if _blocked(idx[q], susp):
                continue
            if (short and h[q] >= level) or (not short and l[q] <= level):
                res.update(status="filled", entry_price=max(level, o[q]) if short else min(level, o[q]),
                           entry_time=idx[q])
                res["x"]["entry"] = q
                break
        if res["status"] == "expired" and fv[fv["idx"] <= fend - 1].empty:
            res["status"] = "trigger, no FVG"
        return res
    return res


# ----------------------------------------------------------------------------- chart
def plot(symbol: str, n: int, st: dict, r5: dict, h1: pd.DataFrame, ltfs: dict, entries: dict, path: Path) -> None:
    short = st["signal"] == "short"
    zc, fc = (BEAR, BULL) if short else (BULL, BEAR)
    fig, axes = plt.subplots(1, 3, figsize=(22, 7), gridspec_kw={"width_ratios": [1, 1.2, 1.2]})
    sig_t = r5["h1_signal_time"]
    b1, t1 = r5["h1_fvg_bottom"], r5["h1_fvg_top"]

    # 1H panel
    ax = axes[0]
    j = h1.index.searchsorted(sig_t) - 1
    df = h1.iloc[max(0, j - 30):min(len(h1), j + 40)]
    draw_candles(ax, df)
    xj = j - max(0, j - 30)
    ax.add_patch(Rectangle((xj - 0.4, b1), len(df) - xj, t1 - b1, facecolor=zc, alpha=0.5, hatch="xx", edgecolor=zc))
    ax.add_patch(Rectangle((0, st["fvg_bottom"]), len(df), st["fvg_top"] - st["fvg_bottom"], facecolor=zc, alpha=0.12,
                           hatch="///", edgecolor=zc, lw=0.4))
    ax.plot(xj, h1["High"].iat[j] if short else h1["Low"].iat[j], "v" if short else "^", color=zc, ms=11, mec="black")
    e0 = next(iter(next(iter(entries.values())).values()))
    ax.set_title(f"1H: 1H IFVG {b1:.2f}-{t1:.2f} (x hatch) inside 4H IFVG (/ hatch) | 1H signal {sig_t:%m-%d %H:%M}"
                 "", fontsize=9)
    _axis(ax, df, "1H")

    for ax, tf in zip(axes[1:], ENTRY_TFS):
        if tf not in entries:
            ax.text(0.5, 0.5, f"{tf}: not selected by entry filter", ha="center", va="center",
                    transform=ax.transAxes, color="gray")
            ax.set_xticks([]); ax.set_yticks([])
            continue
        e_t = entries[tf].get("touch") or next(iter(entries[tf].values()))
        x = e_t["x"]
        if e_t["status"] in ("no data", "no 1H signal"):
            ax.text(0.5, 0.5, f"{tf}: {e_t['status']}", ha="center", va="center", transform=ax.transAxes, color="gray")
            ax.set_xticks([]); ax.set_yticks([])
            continue
        ltf = ltfs[tf]
        s0 = ltf.index.searchsorted(sig_t)
        a = max(0, x.get("origin", s0) - 20)
        last = max([v for k, v in x.items() if isinstance(v, (int, np.integer))] + [s0]) if x else s0 + 60
        b = min(len(ltf), last + 30)
        df = ltf.iloc[a:b]
        draw_candles(ax, df)
        ax.axvline(s0 - a, color="gray", ls=":", lw=0.8)
        ax.add_patch(Rectangle((s0 - a, b1), len(df) - (s0 - a), t1 - b1, facecolor=zc, alpha=0.25, hatch="xx",
                               edgecolor=zc, lw=0.5))
        ax.text(len(df) - 1, t1 if short else b1, "1H IFVG", fontsize=8, color=zc, ha="right",
                va="bottom" if short else "top", fontweight="bold")
        bar = ltf.index[1] - ltf.index[0]
        for s_a, s_b in x.get("susp", []):                     # closed back through, then re-inverted
            xa = df.index.searchsorted(s_a - pd.Timedelta(CLOSE_THROUGH_TF), side="right") - 1
            xb = df.index.searchsorted(s_b - bar, side="right") - 1
            if 0 <= xa < len(df):
                ax.axvspan(xa - 0.5, max(xb, xa) + 0.5, color="orange", alpha=0.35)
        if pd.notna(e_t["cancel_time"]):
            xc = df.index.searchsorted(e_t["cancel_time"] - pd.Timedelta(CLOSE_THROUGH_TF), side="right") - 1
            if 0 <= xc < len(df):
                ax.axvline(xc, color="black", lw=1.2, ls="--")
                ax.text(xc, ax.get_ylim()[0], f" order cancelled ({CLOSE_THROUGH_TF} close back through entry FVG)", fontsize=8,
                        va="bottom")
        if "retest" in x:
            ax.plot(x["retest"] - a, ltf["High"].iat[x["retest"]] if short else ltf["Low"].iat[x["retest"]], "o",
                    mfc="none", mec="black", ms=9, mew=1.5)
        if "hi" in x:
            ax.hlines(e_t["retest_extreme"], x["hi"] - a, len(df), color="black", lw=0.8, ls=":")
            ax.text(len(df) - 1, e_t["retest_extreme"], "cancel above" if short else "cancel below", fontsize=7,
                    ha="right", va="bottom")
            ax.hlines(e_t["trigger_level"], max(x["hi"] - a - 15, 0), x["trig"] - a, color="#6a1b9a", lw=1.3, ls="-.")
            ax.text(max(x["hi"] - a - 15, 0), e_t["trigger_level"], f"{e_t['trigger']} {e_t['trigger_level']:.2f}",
                    fontsize=8, color="#6a1b9a", va="bottom", fontweight="bold")
            ax.axvspan(x["hi"] - a - 0.5, x["trig"] - a + 0.5, color=zc, alpha=0.08)
        if "fvg" in x:
            i1 = x["fvg"] - 2 - a
            ax.add_patch(Rectangle((i1 - 0.4, e_t["fvg_bottom"]), len(df) - i1, e_t["fvg_top"] - e_t["fvg_bottom"],
                                   color=zc, alpha=0.35, lw=0))
            ce = (e_t["fvg_bottom"] + e_t["fvg_top"]) / 2
            ax.hlines(ce, i1, len(df), color="black", lw=0.9, ls="--")
            ax.text(len(df) - 1, ce, "CE", fontsize=7, ha="right", va="center")
        msgs = []
        for name, e in entries[tf].items():
            if e["status"] == "filled":
                q = e["x"]["entry"] - a
                ax.plot(q, e["entry_price"], "v" if short else "^", color=zc if name == "touch" else "white",
                        ms=12, mec="black")
                msgs.append(f"{name} {e['entry_price']:.2f} @ {e['entry_time']:%m-%d %H:%M}")
            else:
                msgs.append(f"{name}: {e['status']}")
        ax.set_title(f"{tf}: trigger {e_t['trigger'] or '-'} | entry " + " | ".join(msgs), fontsize=9)
        _axis(ax, df, tf)
    fig.suptitle(f"{symbol} setup #{n} ({st['signal']}) | shaded box = entry FVG (CE dashed) | "
                 f"coloured marker = touch entry, white = CE entry", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=95)
    plt.close(fig)


# ----------------------------------------------------------------------------- main
def main() -> None:
    (OUT / "setups").mkdir(parents=True, exist_ok=True)
    for old in (OUT / "setups").glob("*.png"):
        old.unlink()
    for symbol, (h1_file, m15_file, m5_file) in SYMBOLS.items():
        h1 = load(DATA / h1_file)
        h4, setups = build_4h_setups(h1)
        h1_fvgs = ifvg.find_fvgs(h1)
        ltfs = {"15m": load(DATA / m15_file), "5m": load(DATA / m5_file)}
        ltf_fvgs = {tf: ifvg.find_fvgs(df) for tf, df in ltfs.items()}
        rows = []
        for n, st in enumerate(setups, 1):
            r5 = find_1h_ifvg(st, h1, h1_fvgs)
            if r5["status"] != "signal":
                continue
            entries = {tf: {m: find_entry(st, r5, h1, ltfs[tf], ltf_fvgs[tf], m, ltfs.get(CLOSE_THROUGH_TF))
                            for m in selected_modes(tf)} for tf in selected_tfs()}
            for tf in entries:
                for m, e in entries[tf].items():
                    rows.append({"setup": n, "signal": st["signal"], "1h_signal_time": r5["h1_signal_time"],
                                 "1h_ifvg_bottom": r5["h1_fvg_bottom"], "1h_ifvg_top": r5["h1_fvg_top"],
                                 "entry_tf": tf, "entry_mode": m, **{k: v for k, v in e.items() if k != "x"}})
            if next(iter(next(iter(entries.values())).values()))["status"] != "no data":
                plot(symbol, n, st, r5, h1, ltfs, entries,
                     OUT / "setups" / f"{symbol}_{n:02d}_{r5['h1_signal_time']:%Y%m%d_%H%M}_{st['signal']}.png")
        res = pd.DataFrame(rows)
        res.to_csv(OUT / f"{symbol}_entries.csv", index=False)
        have = res[res.status != "no data"]
        print(f"\n{symbol}: {res.setup.nunique()} 1H IFVG signals, {have.setup.nunique()} with 15m/5m data")
        if len(have):
            print(have.pivot_table(index=["entry_tf", "entry_mode"], columns="status", values="setup",
                                   aggfunc="count", fill_value=0).to_string())
            trg = have.drop_duplicates(["setup", "entry_tf"]).groupby("entry_tf")["trigger"].value_counts().to_dict()
            print("  triggers:", trg)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    add_entry_arg(ap)
    apply_entry_arg(ap.parse_args())
    print("entry filter:", ", ".join(f"{t} {m}" for t, m in selected_entries()))
    main()
