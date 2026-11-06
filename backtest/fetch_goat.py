"""Convert MT5 M1 exports (any broker) to UTC and build 5m / 15m / 1H files.

Usage:
    .venv/bin/python fetch_goat.py                       # GoatFunded  (data/goat/)
    .venv/bin/python fetch_goat.py --source pepperstone  # Pepperstone (data/pepperstone/)

Input:  data/{source}/{SYMBOL}_M1*.csv   MT5 "Export Bars" (tab separated, BID prices, broker server time).
        Accepted symbol names in the file name: US100 / NAS100 / USTEC and XAUUSD / GOLD.
Output: data/{source}/{SYMBOL}_{1m,5m,15m,1h}.csv  (UTC; columns Open High Low Close Volume Spread)
        data/{source}/costs.json                   median spread per symbol (used as cost by backtest.py)

Server time is assumed to be New York time + 7 hours (GMT+2 in winter, GMT+3 during US daylight saving -
GoatFunded and Pepperstone both use this) and is VERIFIED month by month against the UTC Yahoo data.
Prices are used exactly as exported (the broker's own feed).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent / "data"
ALIASES = {"US100": ["US100", "NAS100", "USTEC", "NDX100"], "XAUUSD": ["XAUUSD", "GOLD"]}
POINT = {"US100": 0.01, "XAUUSD": 0.01}           # default price per MT5 point; refined from the decimals in the file
TFS = {"5m": "5min", "15m": "15min", "1h": "1h"}
AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum", "Spread": "mean"}
YAHOO_REF = {"US100": "US100_NQF_1h_ext.csv", "XAUUSD": "XAUUSD_GCF_1h_ext.csv"}


def server_to_utc(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    ny = (idx - pd.Timedelta(hours=7)).tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
    return ny.tz_convert("UTC")


def find_file(folder: Path, sym: str) -> Path:
    for alias in ALIASES[sym]:
        hits = sorted(p for p in folder.glob("*.csv") if p.name.upper().startswith(alias) and "_M1" in p.name.upper())
        if hits:
            return max(hits, key=lambda p: p.stat().st_size)      # largest = fullest export
    raise FileNotFoundError(f"no M1 export for {sym} in {folder} (expected e.g. {ALIASES[sym][0]}_M1.csv)")


def load(path: Path, sym: str) -> pd.DataFrame:
    d = pd.read_csv(path, sep="\t")
    d.columns = [c.strip("<>").lower() for c in d.columns]
    idx = pd.to_datetime(d["date"] + " " + d["time"], format="%Y.%m.%d %H:%M:%S")
    # MT5 point size = number of decimals as written in the file (read as text: "12911.90" has 2 decimals)
    with open(path) as fh:
        next(fh)
        raw = [ln.split("\t")[5] for _, ln in zip(range(5000), fh)]
    decimals = max((len(x.split(".")[1]) if "." in x else 0) for x in raw)
    point = 10.0 ** -int(decimals) if 0 < decimals < 6 else POINT[sym]
    out = pd.DataFrame({"Open": d["open"].values, "High": d["high"].values, "Low": d["low"].values,
                        "Close": d["close"].values, "Volume": d["tickvol"].values,
                        "Spread": d["spread"].values * point}, index=server_to_utc(pd.DatetimeIndex(idx)))
    out = out[out.index.notna()]
    out = out[~out.index.duplicated()].sort_index()
    out.index.name = "Datetime"
    return out


def verify_timezone(h1: pd.DataFrame, sym: str) -> str:
    """Correlate hourly returns with UTC Yahoo data per month; the converted data should match at offset 0."""
    ref = ROOT / YAHOO_REF[sym]
    if not ref.exists():
        return "skipped (no Yahoo reference data)"
    y = pd.read_csv(ref, index_col=0, parse_dates=True)["Close"]
    y.index = pd.to_datetime(y.index, utc=True)
    bad = []
    for month, part in h1["Close"].groupby(h1.index.to_period("M")):
        best, bc = 0, -1.0
        for off in range(-2, 3):
            a = part.copy()
            a.index = a.index - pd.Timedelta(hours=off)
            j = pd.concat([a.pct_change(), y.pct_change()], axis=1, join="inner").dropna()
            if len(j) > 50:
                c = j.corr().iloc[0, 1]
                if c > bc:
                    best, bc = off, c
        if bc > 0 and best != 0:
            bad.append(f"{month} off by {best:+d}h")
    return "OK - every month aligned with UTC" if not bad else "CHECK: " + ", ".join(bad)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="goat")
    folder = ROOT / ap.parse_args().source
    costs = {}
    for sym in ALIASES:
        src = find_file(folder, sym)
        m1 = load(src, sym)                     # broker feed = the prices orders fill at: not altered
        m1.to_csv(folder / f"{sym}_1m.csv")
        rows = [("1m", len(m1), m1.index[0], m1.index[-1])]
        frames = {}
        for tf, rule in TFS.items():
            df = m1.resample(rule, label="left", closed="left").agg(AGG).dropna(subset=["Open"])
            df.to_csv(folder / f"{sym}_{tf}.csv")
            frames[tf] = df
            rows.append((tf, len(df), df.index[0], df.index[-1]))
        costs[sym] = round(float(m1["Spread"].median()), 4)
        gaps = m1.index.to_series().diff()
        big = gaps[gaps > pd.Timedelta(days=4)]
        print(f"{sym}: from {src.name} | median spread {costs[sym]} | timezone: {verify_timezone(frames['1h'], sym)}")
        for tf, n, a, b in rows:
            print(f"   {tf:>3}: {n:>9,} candles  {a:%Y-%m-%d %H:%M} -> {b:%Y-%m-%d %H:%M} UTC")
        for t, g in big.items():
            print(f"   data gap: {t - g:%Y-%m-%d} -> {t:%Y-%m-%d} ({g.days} days)")
    (folder / "costs.json").write_text(json.dumps(costs, indent=2))


if __name__ == "__main__":
    main()
