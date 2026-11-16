"""Rule 3: 4H IFVG = setup. Lower timeframes (1H / 15m / 5m) = OTE entry.

Usage:
    .venv/bin/python ote.py

Setup (4H only):
    D/W/M swing level swept -> FVG left in the leg -> FVG inverted (see ifvg.py).
    Signal is known at the CLOSE of the 4H inversion candle.

Entry (each lower timeframe separately: 1H, 15m, 5m) - ICT Optimal Trade Entry:
    SHORT (high was swept):
        range high = highest price of the 4H leg (the sweep extreme), located on the LTF
        range low  = lowest LTF low since that high (keeps updating while price extends lower)
        OTE zone   = 62% - 79% retracement back up from the low; entry limit at 70.5%
        A bar that makes a new range low does not trigger an entry (conservative: the order
        of high/low inside a bar is unknown) - the zone is recalculated and we wait.
    LONG (low was swept): mirror image.
    Cancelled if price trades beyond the range extreme (high for shorts / low for longs) before
    the fill, or if no fill within ENTRY_EXPIRY after the 4H signal.

Outputs:
    output/ote/{SYMBOL}_4H.png                    4H chart with sweeps + IFVGs (only TF with IFVGs)
    output/ote/{SYMBOL}_ote_entries.csv           every 4H setup x LTF with entry result
    output/ote/setups/{SYMBOL}_{n}_{date}.png     per-setup panel: 4H | 1H | 15m | 5m
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
from swings import DATA, STYLE, SYMBOLS, add_break_times, build_htf, draw_candles, find_swings, load, refine_breaks

# ----------------------------------------------------------------------------- CONFIG
OTE_LOW, OTE_ENTRY, OTE_HIGH = 0.62, 0.705, 0.79
ENTRY_TFS = ["1H", "15m", "5m"]
# Rule 4 entry options
ENTRY_EXPIRY = pd.Timedelta(hours=48)   # (a) 12 x 4H candles after the signal (was 24h)
USE_IFVG_RETEST = True                  # (b) also place a limit at the IFVG near edge; first touched fills
OTE_RANGE = "leg"                       # (c) "leg" = LTF displacement leg, "sweep" = 4H sweep extreme
LTF_PIVOT = 2                           #     swing size used to find the LTF leg high/low

OUT = Path(__file__).parent / "output" / "ote"
BULL, BEAR, OTE_C = "#26a69a", "#ef5350", "#ffb300"
H4 = pd.Timedelta(hours=4)


# ----------------------------------------------------------------------------- entry
_piv_cache: dict[int, tuple] = {}


def _ltf_arrays(ltf: pd.DataFrame):
    """OHLC arrays + confirmed LTF pivot highs/lows (cached per frame)."""
    key = id(ltf)
    if key not in _piv_cache:
        o, h, l, c = (ltf[k].to_numpy() for k in ("Open", "High", "Low", "Close"))
        p, n = LTF_PIVOT, len(ltf)
        w = 2 * p + 1
        hmax = pd.Series(h).rolling(w, center=True).max().to_numpy()
        lmin = pd.Series(l).rolling(w, center=True).min().to_numpy()
        ph = np.where(h == hmax)[0]
        pl = np.where(l == lmin)[0]
        _piv_cache[key] = (o, h, l, c, ph[(ph >= p) & (ph < n - p)], pl[(pl >= p) & (pl < n - p)])
    return _piv_cache[key]


def find_ote_entry(setup: dict, ltf: pd.DataFrame) -> dict:
    """Walk LTF bars after the 4H signal; fill at the OTE level and/or the IFVG retest.

    SHORT: extreme = LTF high of the 4H sweep extreme; running low = lowest low since then.
      leg high = (c) last confirmed LTF swing high between the extreme and the running low
                 (falls back to the extreme), or the extreme itself when OTE_RANGE="sweep".
      OTE entry = low + 70.5% x (leg high - low). IFVG entry = IFVG bottom (near edge).
      Whichever is lower is touched first while price retraces up -> that order fills.
    LONG mirror image. Bars that make a new running extreme never fill (intra-bar order unknown).
    Cancelled if price trades beyond the sweep extreme, or no fill within ENTRY_EXPIRY.
    """
    short = setup["signal"] == "short"
    res = {"status": "no data", "entry_type": "", "entry_time": pd.NaT, "entry_price": np.nan,
           "range_high": np.nan, "range_low": np.nan, "anchor_time": pd.NaT, "leg_time": pd.NaT}
    sig_t, ext_t = setup["signal_time"], setup["extreme_time"]
    idx = ltf.index
    if idx[0] > ext_t or idx[-1] < sig_t:
        return res
    o, h, l, c, ph, pl = _ltf_arrays(ltf)
    a0, a1 = idx.searchsorted(ext_t), idx.searchsorted(ext_t + H4)
    s0, end = idx.searchsorted(sig_t), min(idx.searchsorted(sig_t + ENTRY_EXPIRY), len(ltf))
    if a1 <= a0 or s0 <= a0:
        return res
    anchor = a0 + int(np.argmax(h[a0:a1]) if short else np.argmin(l[a0:a1]))
    extreme = h[anchor] if short else l[anchor]
    seg = slice(anchor, s0)
    run_i = anchor + int(np.argmin(l[seg]) if short else np.argmax(h[seg]))
    running = l[run_i] if short else h[run_i]
    ifvg_edge = setup["fvg_bottom"] if short else setup["fvg_top"]
    piv = ph if short else pl
    res.update(anchor_time=idx[anchor], status="expired")

    def leg_point(p: int) -> int:
        if OTE_RANGE != "leg":
            return anchor
        cand = piv[(piv >= anchor) & (piv <= run_i) & (piv + LTF_PIVOT < p)]
        return int(cand[-1]) if len(cand) else anchor

    leg_i = leg_point(s0)
    for p in range(s0, end):
        if (short and h[p] > extreme) or (not short and l[p] < extreme):
            res["status"] = "invalidated"
            break
        if (short and l[p] < running) or (not short and h[p] > running):
            running, run_i = (l[p], p) if short else (h[p], p)
            continue
        leg_i = leg_point(p)
        leg = h[leg_i] if short else l[leg_i]
        ote = running + (leg - running) * OTE_ENTRY if short else running - (running - leg) * OTE_ENTRY
        orders = [("OTE", ote)]
        if USE_IFVG_RETEST:
            orders.append(("IFVG", ifvg_edge))
        kind, lvl = min(orders, key=lambda x: x[1]) if short else max(orders, key=lambda x: x[1])
        if (short and h[p] >= lvl) or (not short and l[p] <= lvl):
            fill = max(lvl, o[p]) if short else min(lvl, o[p])   # gap through the level -> fill at open
            res.update(status="filled", entry_type=kind, entry_time=idx[p], entry_price=fill)
            break
    leg = h[leg_i] if short else l[leg_i]
    res.update(range_high=leg if short else running, range_low=running if short else leg, leg_time=idx[leg_i])
    return res


def ote_levels(short: bool, hi: float, lo: float) -> tuple[float, float, float]:
    rng = hi - lo
    if short:
        return lo + rng * OTE_LOW, lo + rng * OTE_ENTRY, lo + rng * OTE_HIGH
    return hi - rng * OTE_LOW, hi - rng * OTE_ENTRY, hi - rng * OTE_HIGH


# ----------------------------------------------------------------------------- per-setup chart
def _axis(ax, df, tf):
    step = max(len(df) // 8, 1)
    ticks = list(range(0, len(df), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([df.index[i].strftime("%m-%d %H:%M") for i in ticks], rotation=25, ha="right", fontsize=7)
    ax.set_xlim(-1, len(df) + 1)
    ax.grid(alpha=0.15)


def draw_4h_panel(ax, st: dict, h4: pd.DataFrame) -> None:
    """4H setup: swept level, FVG, IFVG, displacement, CISD/MSS, signal."""
    short = st["signal"] == "short"
    zone_c = BEAR if short else BULL
    s, j, i3 = st["x_sweep_idx"], st["x_inv_idx"], st["x_fvg_idx"]
    a, b = max(0, min(s, i3 - 2) - 25), min(len(h4), j + 15)
    df = h4.iloc[a:b]
    draw_candles(ax, df)
    lv_tf, lv_type, lv_price, _ = st["x_levels"][0]
    ax.hlines(lv_price, 0, s - a, color=STYLE[lv_tf][0], lw=1.6, ls="-" if lv_type == "high" else "--")
    ax.plot(s - a, lv_price, "x", color=STYLE[lv_tf][0], ms=8, mew=2)
    ax.add_patch(Rectangle((i3 - 2 - a - 0.4, st["fvg_bottom"]), j - (i3 - 2) + 0.4, st["fvg_top"] - st["fvg_bottom"],
                           color=BULL if short else BEAR, alpha=0.25, lw=0))
    ax.add_patch(Rectangle((j - a - 0.4, st["fvg_bottom"]), b - j, st["fvg_top"] - st["fvg_bottom"],
                           facecolor=zone_c, alpha=0.45, hatch="///", edgecolor=zone_c, lw=0.8))
    ax.plot(j - a, h4["High"].iat[j] if short else h4["Low"].iat[j], "v" if short else "^", color=zone_c, ms=11)
    # rule 4: displacement candles + CISD / MSS levels
    xd = int(h4.index.get_loc(st["disp_start_time"])) - a
    ax.axvspan(xd - 0.5, j - a + 0.5, color=zone_c, alpha=0.08)
    ax.text(xd, ax.get_ylim()[0], f" displacement {st['disp_candles']}c / {st['disp_atr']} ATR", fontsize=7,
            color=zone_c, va="bottom")
    xe = st["x_ext_idx"] - a
    for name, lvl, t, col in (("CISD", st["cisd_level"], st["cisd_time"], "#6a1b9a"),
                              ("MSS", st["mss_level"], st["mss_time"], "#00838f")):
        if pd.isna(lvl):
            continue
        ok = pd.notna(t)
        x1 = int(h4.index.get_loc(t)) - a if ok else j - a
        ax.hlines(lvl, max(xe - 8, 0), x1, color=col, lw=1.2, ls="-." if ok else ":", alpha=0.9 if ok else 0.4)
        ax.text(max(xe - 8, 0), lvl, f"{name} {lvl:.2f}{'' if ok else ' (not broken)'}", fontsize=7, color=col,
                va="bottom", fontweight="bold" if ok else "normal")
    lvls = st["swept_levels"].split(", ")
    lvls_txt = ", ".join(lvls[:2]) + (f" +{len(lvls) - 2} more" if len(lvls) > 2 else "")
    ax.set_title(f"4H: {lvls_txt} swept -> {'bearish' if short else 'bullish'} IFVG "
                 f"{st['fvg_bottom']:.2f}-{st['fvg_top']:.2f} | {st['confirm']} | {st['signal'].upper()} @ "
                 f"{st['signal_time']:%Y-%m-%d %H:%M}", fontsize=9)
    _axis(ax, df, "4H")



def plot_setup(symbol: str, n: int, st: dict, h4: pd.DataFrame, ltfs: dict, entries: dict, path: Path) -> None:
    short = st["signal"] == "short"
    zone_c = BEAR if short else BULL
    fig, axes = plt.subplots(2, 2, figsize=(18, 10))

    draw_4h_panel(axes[0, 0], st, h4)

    # --- LTF panels
    for ax, tf in zip([axes[0, 1], axes[1, 0], axes[1, 1]], ENTRY_TFS):
        ltf, e = ltfs[tf], entries[tf]
        if e["status"] == "no data":
            ax.text(0.5, 0.5, f"{tf}: no data for this date\n(Yahoo keeps only ~60 days of {tf})",
                    ha="center", va="center", transform=ax.transAxes, fontsize=11, color="gray")
            ax.set_xticks([]); ax.set_yticks([])
            continue
        t0 = e["anchor_time"] - (ltf.index[1] - ltf.index[0]) * 20
        t1 = (e["entry_time"] if pd.notna(e["entry_time"]) else st["signal_time"] + ENTRY_EXPIRY) + (ltf.index[1] - ltf.index[0]) * 25
        df = ltf[(ltf.index >= t0) & (ltf.index <= t1)]
        draw_candles(ax, df)
        x = lambda ts: int(df.index.searchsorted(ts))
        xs = x(st["signal_time"])
        # 4H IFVG projected
        ax.add_patch(Rectangle((xs, st["fvg_bottom"]), len(df) - xs, st["fvg_top"] - st["fvg_bottom"],
                               facecolor=zone_c, alpha=0.25, hatch="///", edgecolor=zone_c, lw=0.6))
        ax.axvline(xs, color="gray", lw=0.8, ls=":")
        # sweep extreme (invalidation) + OTE range (LTF leg) + OTE zone
        sweep_ext = ltf.loc[e["anchor_time"], "High" if short else "Low"]
        ax.hlines(sweep_ext, x(e["anchor_time"]), len(df), color="black", lw=0.8, ls=":")
        ax.text(len(df), sweep_ext, " invalidation", fontsize=7, va="center")
        xa = x(e["leg_time"])
        z_lo, z_mid, z_hi = ote_levels(short, e["range_high"], e["range_low"])
        ax.hlines([e["range_high"], e["range_low"]], xa, len(df), color="black", lw=0.9, ls="-")
        if pd.notna(e["leg_time"]):
            ax.plot(xa, e["range_high"] if short else e["range_low"], "o", color="black", ms=5)
        ax.add_patch(Rectangle((xs, min(z_lo, z_hi)), len(df) - xs, abs(z_hi - z_lo), color=OTE_C, alpha=0.3, lw=0))
        ax.hlines(z_mid, xs, len(df), color=OTE_C, lw=1.4, ls="--")
        ax.text(len(df), z_mid, " 70.5%", fontsize=7, color="#b27b00", va="center")
        if e["status"] == "filled":
            xe = x(e["entry_time"])
            ax.plot(xe, e["entry_price"], "v" if short else "^", color=zone_c, ms=12, mec="black")
            msg = f"{e['entry_type']} ENTRY {e['entry_price']:.2f} @ {e['entry_time']:%m-%d %H:%M}"
        else:
            msg = e["status"].upper()
        ax.set_title(f"{tf} | leg {e['range_low']:.2f}-{e['range_high']:.2f} | OTE "
                     f"zone {min(z_lo, z_hi):.2f}-{max(z_lo, z_hi):.2f} | {msg}", fontsize=9)
        _axis(ax, df, tf)

    fig.suptitle(f"{symbol} setup #{n}  ({st['signal']})   dotted line = 4H signal close   "
                 f"hatched = 4H IFVG   yellow = OTE 62-79% of LTF leg (black lines, dot = leg start)   "
                 f"window {int(ENTRY_EXPIRY.total_seconds() // 3600)}h", fontsize=10)
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
        htf = {tf: build_htf(h1, tf) for tf in ("D", "W", "M", "4H")}
        levels = pd.concat([find_swings(htf[tf], tf) for tf in ("M", "W", "D")], ignore_index=True)
        h4_full = htf["4H"]
        h4 = h4_full.drop(columns=["Start", "End"])
        lv4 = add_break_times(levels, h4)
        raw = ifvg.find_setups(h4, lv4, "4H")                              # rule 2 only
        setups = ifvg.find_setups(h4, lv4, "4H", accept=structure.quality)  # + rule 4 filter
        ifvg.plot(symbol, "4H", h4, setups, lv4, OUT / f"{symbol}_4H.png")

        # rule 4 report: why each raw (first-inversion) setup passed / failed
        diag = pd.DataFrame([{
            "signal": r["signal"], "inversion_time": r["inversion_time"], "swept_levels": r["swept_levels"],
            **{k: v for k, v in structure.quality(h4, {"inv_idx": r["x_inv_idx"]}, r["x_sweep_idx"],
                                                  "bull" if r["signal"] == "short" else "bear").items()
               if not k.startswith("x_")}} for r in raw.to_dict("records")])
        diag.to_csv(OUT / f"{symbol}_rule4_filter.csv", index=False)
        n_disp = int((diag["disp_candles"] >= structure.DISP_MIN_CANDLES).sum())
        print(f"\n{symbol}: {len(raw)} raw 4H IFVGs -> {len(setups)} pass rule 4 "
              f"(first inversion: {int(diag['passed'].sum())} pass, "
              f"{int(diag['reject_reason'].str.contains('displacement').sum())} weak displacement, "
              f"{int(diag['reject_reason'].str.contains('CISD').sum())} no CISD/MSS)")
        if setups.empty:
            continue
        print("  confirmations:", setups["confirm"].value_counts().to_dict())

        ltfs = {"1H": h1, "15m": load(DATA / m15_file), "5m": load(DATA / m5_file)}
        rows, setups_prepared = [], []
        for n, st in enumerate(setups.to_dict("records"), 1):
            j = st["x_inv_idx"]
            st["signal_time"] = h4_full["End"].iat[j]
            seg = h4.iloc[st["x_sweep_idx"]:j + 1]
            st["extreme_time"] = seg["High"].idxmax() if st["signal"] == "short" else seg["Low"].idxmin()
            setups_prepared.append(st)
            entries = {tf: find_ote_entry(st, ltfs[tf]) for tf in ENTRY_TFS}
            for tf, e in entries.items():
                rows.append({"setup": n, "signal": st["signal"], "signal_time": st["signal_time"],
                             "swept_levels": st["swept_levels"], "ifvg_bottom": st["fvg_bottom"],
                             "ifvg_top": st["fvg_top"], "confirm": st["confirm"],
                             "disp_candles": st["disp_candles"], "disp_atr": st["disp_atr"],
                             "entry_tf": tf, **e})
            plot_setup(symbol, n, st, h4, ltfs, entries,
                       OUT / "setups" / f"{symbol}_{n:02d}_{st['signal_time']:%Y%m%d_%H%M}_{st['signal']}.png")
        res = pd.DataFrame(rows)
        res.to_csv(OUT / f"{symbol}_ote_entries.csv", index=False)
        summary = res.pivot_table(index="entry_tf", columns="status", values="setup", aggfunc="count", fill_value=0)
        print(summary.reindex(ENTRY_TFS).to_string())
        f = res[res.status == "filled"]
        print("  filled by:", f.groupby("entry_tf")["entry_type"].value_counts().unstack(fill_value=0)
              .reindex(ENTRY_TFS).fillna(0).astype(int).to_dict("index"))
        compare_variants(symbol, setups_prepared, ltfs)


def compare_variants(symbol: str, setups: list[dict], ltfs: dict) -> None:
    """Fill counts for each entry option on its own and combined."""
    g = globals()
    saved = (g["ENTRY_EXPIRY"], g["USE_IFVG_RETEST"], g["OTE_RANGE"])
    variants = {
        "baseline: 24h, OTE of sweep range": (24, False, "sweep"),
        "(a) 48h window": (48, False, "sweep"),
        "(b) + IFVG retest": (24, True, "sweep"),
        "(c) OTE of LTF leg": (24, False, "leg"),
        "(a)+(b)+(c)": (48, True, "leg"),
    }
    rows = []
    for name, (hrs, retest, rng) in variants.items():
        g["ENTRY_EXPIRY"], g["USE_IFVG_RETEST"], g["OTE_RANGE"] = pd.Timedelta(hours=hrs), retest, rng
        row = {"variant": name}
        for tf in ENTRY_TFS:
            r = [find_ote_entry(st, ltfs[tf])["status"] for st in setups]
            have = sum(s != "no data" for s in r)
            row[tf] = f"{r.count('filled')}/{have}"
        rows.append(row)
    g["ENTRY_EXPIRY"], g["USE_IFVG_RETEST"], g["OTE_RANGE"] = saved
    print(f"  fills per entry option (filled / setups with data):")
    print("   " + pd.DataFrame(rows).to_string(index=False).replace("\n", "\n   "))


if __name__ == "__main__":
    main()
