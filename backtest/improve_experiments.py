"""More trades? Loosen one rule at a time (US100), swing + intraday, plus a direct 4H IFVG swing entry.

Usage:
    DATA_SOURCE=pepperstone_oos TEST_START=2021-04-01 .venv/bin/python improve_experiments.py
Writes output/improve_{source}.csv (one row per trade, all variants).
"""
import contextlib
import io

import numpy as np
import pandas as pd

import backtest as B
import ifvg
import ifvg_1h
import structure
import swing as W
import swings as S

B.plot_trade = lambda *a, **k: None
W.plot_trade = lambda *a, **k: None
H = pd.Timedelta(hours=1)

BASE = dict(inv4=20, disp_atr=1.0, disp_n=2, retest4=48, inv1=20, into=True)
VARIANTS = {
    "BASE (current rules)": {},
    "4H inversion window 30 candles": dict(inv4=30),
    "displacement >= 0.5 ATR": dict(disp_atr=0.5),
    "displacement >= 1 candle": dict(disp_n=1),
    "4H IFVG retest window 72h": dict(retest4=72),
    "1H inversion window 30 candles": dict(inv1=30),
    "FVG into sweep OFF": dict(into=False),
    "LOOSE: inv 30 + 0.5 ATR + retest 72h + 1H inv 30": dict(inv4=30, disp_atr=0.5, retest4=72, inv1=30),
}


def apply(v: dict) -> None:
    p = {**BASE, **v}
    ifvg.INVERT_WINDOW = p["inv4"]
    structure.DISP_MIN_ATR = p["disp_atr"]
    structure.DISP_MIN_CANDLES = p["disp_n"]
    ifvg_1h.RETEST_WINDOW = pd.Timedelta(hours=p["retest4"])
    ifvg_1h.INVERT_WINDOW_1H = p["inv1"]
    ifvg.FVG_INTO_SWEEP = p["into"]
    structure._cache.clear()


def direct_4h_entries(sym: str, h1: pd.DataFrame, setups: list[dict]) -> list[dict]:
    """Swing entry straight at the 4H IFVG retest (no 1H confirmation): limit at the 4H IFVG near edge,
    valid 48h after the 4H signal, stop beyond the 4H sweep extreme, 3R, breakeven at +1R."""
    o, h, l = h1["Open"].to_numpy(), h1["High"].to_numpy(), h1["Low"].to_numpy()
    idx, out = h1.index, []
    for st in setups:
        short = st["signal"] == "short"
        edge = st["fvg_bottom"] if short else st["fvg_top"]
        seg = h1[(idx >= st["extreme_time"]) & (idx < st["extreme_time"] + 4 * H)]
        if seg.empty:
            continue
        ext = seg["High"].max() if short else seg["Low"].min()
        q0, q1 = idx.searchsorted(st["signal_time"]), min(idx.searchsorted(st["signal_time"] + 48 * H), len(h1))
        for q in range(q0, q1):
            if (short and o[q] > ext) or (not short and o[q] < ext):
                break
            if (short and h[q] >= edge) or (not short and l[q] <= edge):
                entry = max(edge, o[q]) if short else min(edge, o[q])
                sl = ext + B.SL_BUFFER[sym] if short else ext - B.SL_BUFFER[sym]
                risk = abs(entry - sl)
                if (short and sl <= entry) or (not short and sl >= entry):
                    break
                tp = entry - 3 * risk if short else entry + 3 * risk
                sim = W.simulate(h1, q, short, entry, sl, tp)
                pnl = (entry - sim["price"]) if short else (sim["price"] - entry)
                out.append({"symbol": sym, "signal": st["signal"], "entry_time": idx[q], "exit_time": idx[sim["k"]],
                            "exit": sim["exit"], "r_net": (pnl - B.COST[sym]) / risk})
                break
    return out


def main() -> None:
    rows = []
    for name, v in VARIANTS.items():
        apply(v)
        with contextlib.redirect_stdout(io.StringIO()):
            t = B.run()
            w, _ = W.run()
        t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")] if len(t) else t
        w = w[(w.entry_type == "1H touch") & (w.stop_type == "4H extreme") & (w.target_type == "3R")] if len(w) else w
        for model, df in (("intraday 5m touch", t), ("swing 1H touch", w)):
            for r in df.itertuples(index=False):
                rows.append({"source": S.DATA_SOURCE, "variant": name, "model": model, "symbol": r.symbol,
                             "entry_time": r.entry_time, "exit_time": r.exit_time, "exit": r.exit, "r_net": r.r_net})
        for sym, (f1, _, _) in S.SYMBOLS.items():
            h1 = S.load(S.DATA / f1)
            _, setups = ifvg_1h.build_4h_setups(h1)
            for r in direct_4h_entries(sym, h1, setups):
                rows.append({"source": S.DATA_SOURCE, "variant": name, "model": "swing 4H IFVG touch (no 1H step)", **r})
        print("done:", name, flush=True)
    apply({})
    pd.DataFrame(rows).to_csv(f"output/improve_{S.DATA_SOURCE}.csv", index=False)


if __name__ == "__main__":
    main()
