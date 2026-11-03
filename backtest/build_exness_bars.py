"""Build US100 candles from the Exness ticks (data/exness_ticks/*.npz) -> data/exness/.

Usage:
    .venv/bin/python build_exness_bars.py
Bars are built from the BID (like MT5 charts), UTC timestamps, 1m -> 5m / 15m / 1H by resampling the 1m bars.
Volume = number of ticks, Spread = mean ask - bid in the bar.
costs.json: US100 cost per trade = median spread (price units) on the 1m bars (Exness standard account, no commission).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
TICKS = HERE / "data" / "exness_ticks"
OUT = HERE / "data" / "exness"
SYM = os.environ.get("EXNESS_SYMBOL", "USTEC")             # Exness symbol -> our symbol name
NAME = {"USTEC": "US100", "XAUUSD": "XAUUSD"}[SYM]


def month_bars(f: Path) -> pd.DataFrame:
    z = np.load(f)
    t = z["t"]
    if len(t) and t[0] < 10**11:
        t = t * 1000
    bid, ask = z["bid"], z["ask"]
    minute = (t // 60000) * 60000
    df = pd.DataFrame({"m": minute, "bid": bid, "spr": ask - bid})
    g = df.groupby("m", sort=True)
    out = pd.DataFrame({"Open": g["bid"].first(), "High": g["bid"].max(), "Low": g["bid"].min(),
                        "Close": g["bid"].last(), "Volume": g["bid"].size(), "Spread": g["spr"].mean()})
    out.index = pd.to_datetime(out.index, unit="ms", utc=True)
    out.index.name = "Datetime"
    return out


def resample(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    r = m1.resample(rule, label="left", closed="left")
    out = pd.DataFrame({"Open": r["Open"].first(), "High": r["High"].max(), "Low": r["Low"].min(),
                        "Close": r["Close"].last(), "Volume": r["Volume"].sum(), "Spread": r["Spread"].mean()})
    return out.dropna(subset=["Open"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(TICKS.glob(f"{SYM}_*.npz"))
    parts = []
    for f in files:
        parts.append(month_bars(f))
        print(f.name, len(parts[-1]), flush=True)
    m1 = pd.concat(parts).sort_index()
    m1 = m1[~m1.index.duplicated(keep="first")]
    m1.to_csv(OUT / f"{NAME}_1m.csv")
    for rule, name in (("5min", "5m"), ("15min", "15m"), ("1h", "1h")):
        resample(m1, rule).to_csv(OUT / f"{NAME}_{name}.csv")
    cost = round(float(m1["Spread"].median()), 2)
    cf = OUT / "costs.json"
    costs = json.loads(cf.read_text()) if cf.exists() else {}
    costs[NAME] = cost
    cf.write_text(json.dumps(costs, indent=2))
    print("1m bars", len(m1), m1.index[0], "->", m1.index[-1], "| median spread", cost)


if __name__ == "__main__":
    main()
