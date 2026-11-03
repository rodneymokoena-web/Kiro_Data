"""Regenerate the US100 2021-2026 result files with the current default rules.

Usage:
    .venv/bin/python make_us100_results.py            # runs the 4 data sets (in parallel) and combines them
Writes:
    output/us100_summary_2021_2026.csv
    output/us100_{broker}_{model}_trades_2021_2026.csv   full trade rows
    output/us100_{broker}_{model}_levels.csv             entry / stop / target per trade
    models: swing (main, swing_snap.py: last 4H FVG of the sweeping leg inverted by a 1H close + 1H MSS, entry at the
            4H IFVG, stop above the 1H OB 50%, target 1H swing low), intraday (5m touch, prev 1H candle stop, 3R),
            swing_prev (previous swing model swing.py: 1H IFVG entry, 4H order block stop, 3R - reference only)
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "output"
RUNS = OUT / "us100_runs"
SOURCES = {"goat": "2024-01-01", "pepperstone": "2024-01-01", "goat_oos": "2021-04-01", "pepperstone_oos": "2021-04-01"}
BROKER = {"goat": "GoatFunded", "pepperstone": "Pepperstone"}
START, RISK = 10_000, 0.01


def run_source(src: str) -> None:
    import backtest as B
    import swing as W
    import swing_snap as SN
    B.plot_trade = lambda *a, **k: None
    W.plot_trade = lambda *a, **k: None
    period = "unseen" if src.endswith("oos") else "tuned"
    RUNS.mkdir(parents=True, exist_ok=True)
    SN.run().assign(period=period).to_csv(RUNS / f"{src}_swing.csv", index=False)
    W.RULE3 = "4H close"
    with contextlib.redirect_stdout(io.StringIO()):
        w, _ = W.run()
    w = w[(w.entry_type == "1H touch") & (w.stop_type == W.MAIN_STOP) & (w.target_type == "3R")]
    w.assign(period=period).to_csv(RUNS / f"{src}_swing_prev.csv", index=False)
    with contextlib.redirect_stdout(io.StringIO()):
        t = B.run()
    t = t[(t.entry_tf == "5m") & (t.entry_mode == "touch")].rename(columns={"entry_price": "entry"})
    t.assign(period=period).to_csv(RUNS / f"{src}_intraday.csv", index=False)


def stats(r: pd.Series) -> dict:
    r = r.reset_index(drop=True)
    eq = START * np.cumprod(1 + RISK * r.to_numpy())
    curve = np.r_[START, eq]
    peak = np.maximum.accumulate(curve)
    win, loss = r[r > 0].sum(), -r[r < 0].sum()
    return {"trades": len(r), "W": int((r > 0.2).sum()), "L": int((r < -0.2).sum()), "BE": int((r.abs() <= 0.2).sum()),
            "PF": round(win / loss, 2) if loss else np.inf, "R": round(r.sum(), 2),
            "account": int(round(curve[-1])), "maxDD%": round(((peak - curve) / peak).max() * 100, 1)}


def combine() -> None:
    rows, both = [], {}
    for key, broker in BROKER.items():
        for model in ("swing", "intraday", "swing_prev"):
            d = pd.concat([pd.read_csv(RUNS / f"{s}_{model}.csv") for s in (f"{key}_oos", key)], ignore_index=True)
            d["entry_time"] = pd.to_datetime(d["entry_time"], utc=True)
            d = d.sort_values("entry_time").reset_index(drop=True)
            d.to_csv(OUT / f"us100_{broker.lower()}_{model}_trades_2021_2026.csv", index=False)
            exit_ = np.where((d["exit"] == "stop") & (d["r_net"] > -0.2), "breakeven", d["exit"])
            lv = pd.DataFrame({"#": range(1, len(d) + 1), "entry time (UTC)": d["entry_time"].dt.strftime("%Y-%m-%d %H:%M"),
                               "dir": d["signal"].str.upper(), "entry": d["entry"].round(1), "stop": d["stop"].round(1),
                               "target": d["target"].round(1), "risk_pts": d["risk_pts"].round(1), "exit": exit_,
                               "exit time": pd.to_datetime(d["exit_time"], utc=True).dt.strftime("%Y-%m-%d"),
                               "R": d["r_net"].round(2)})
            lv.to_csv(OUT / f"us100_{broker.lower()}_{model}_levels.csv", index=False)
            label = "swing (previous model)" if model == "swing_prev" else model
            for per in ("tuned", "unseen"):
                rows.append({"broker": broker, "model": label, "period": per, **stats(d[d.period == per]["r_net"])})
            rows.append({"broker": broker, "model": label, "period": "2021-26", **stats(d["r_net"])})
            if model != "swing_prev":
                both.setdefault(broker, []).append(d[["entry_time", "r_net"]])
        b = pd.concat(both[broker]).sort_values("entry_time")
        rows.append({"broker": broker, "model": "both (1% each)", "period": "2021-26", **stats(b["r_net"])})
    s = pd.DataFrame(rows)
    s.to_csv(OUT / "us100_summary_2021_2026.csv", index=False)
    pd.set_option("display.width", 200)
    print(s.to_string(index=False))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_source(sys.argv[1])
    else:
        procs = [subprocess.Popen([sys.executable, __file__, s], env={**os.environ, "DATA_SOURCE": s, "TEST_START": ts,
                                                                       "MPLCONFIGDIR": "/tmp/mpl"})
                 for s, ts in SOURCES.items()]
        if any(p.wait() for p in procs):
            sys.exit("a data set failed")
        combine()
