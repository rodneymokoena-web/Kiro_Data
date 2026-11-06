"""Download 1-minute BID/ASK candles from Dukascopy and build 5m/15m/1h/1d bars.

Usage:
    .venv/bin/python fetch_dukascopy.py            # download + build
    .venv/bin/python fetch_dukascopy.py --build    # rebuild bars from cache only

Instruments:
    US100   -> USATECHIDXUSD (Dukascopy US Tech 100 CFD)
    XAUUSD  -> XAUUSD        (spot gold)

Output (data/dukascopy/):
    {NAME}_{tf}.csv  with columns:
        Datetime (UTC), Open, High, Low, Close   <- BID prices (like MT4/MT5 charts)
        Volume                                    <- Dukascopy tick volume
        Spread                                    <- avg (ASK close - BID close) in price units

Notes:
    * Raw daily .bi5 files are cached in data/dukascopy/raw so re-runs resume.
    * Dukascopy pads closed-market minutes with flat zero-volume candles; these are dropped.
    * Daily bars use the FX-standard 17:00 New York rollover (same as most CFD brokers),
      labelled by the trading date they close on.
"""
from __future__ import annotations

import argparse
import lzma
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

START = "2026-01-01"
END = None  # None = yesterday (UTC); today's file isn't published until the day ends

INSTRUMENTS = {
    "US100": ("USATECHIDXUSD", 1000),
    "XAUUSD": ("XAUUSD", 1000),
}
SIDES = ["BID", "ASK"]
TIMEFRAMES = {"5m": "5min", "15m": "15min", "1h": "1h"}

URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/{side}_candles_min_1.bi5"
OUT_DIR = Path(__file__).parent / "data" / "dukascopy"
RAW_DIR = OUT_DIR / "raw"
WORKERS = 5
MAX_RETRIES = 8


# ----------------------------------------------------------------------------- download
def raw_path(sym: str, day: pd.Timestamp, side: str) -> Path:
    return RAW_DIR / sym / f"{day:%Y-%m-%d}_{side}.bi5"


def download_day(sym: str, day: pd.Timestamp, side: str) -> tuple[str, str]:
    path = raw_path(sym, day, side)
    if path.exists():
        return str(path), "cached"
    # Dukascopy months are 0-indexed
    url = URL.format(sym=sym, y=day.year, m=day.month - 1, d=day.day, side=side)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    delay = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)  # empty file = no data that day (valid)
            return str(path), "ok"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
                return str(path), "404"
            err = f"HTTP {e.code}"
        except Exception as e:  # timeouts, resets
            err = type(e).__name__
        time.sleep(delay)
        delay = min(delay * 1.8, 60)
    return str(path), f"FAILED ({err})"


def trading_days() -> list[pd.Timestamp]:
    end = pd.Timestamp(END) if END else pd.Timestamp.now(tz="UTC").normalize().tz_localize(None) - pd.Timedelta(days=1)
    days = pd.date_range(START, end, freq="D")
    return [d for d in days if d.dayofweek != 5]  # Saturdays: both markets closed


def download_all() -> bool:
    jobs = [(sym, d, side) for sym, _ in INSTRUMENTS.values() for d in trading_days() for side in SIDES]
    todo = [j for j in jobs if not raw_path(*j).exists()]
    print(f"{len(jobs)} files total, {len(jobs) - len(todo)} cached, {len(todo)} to download", flush=True)
    failed = []
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(download_day, *j): j for j in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            _, status = fut.result()
            if status.startswith("FAILED"):
                failed.append((futures[fut], status))
            if i % 50 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} done, {len(failed)} failed", flush=True)
    for (sym, d, side), status in failed:
        print(f"  FAILED: {sym} {d:%Y-%m-%d} {side}: {status}")
    return not failed


# ----------------------------------------------------------------------------- decode/build
def decode(path: Path, day: pd.Timestamp, scale: int) -> pd.DataFrame:
    blob = path.read_bytes() if path.exists() else b""
    if not blob:
        return pd.DataFrame()
    raw = lzma.decompress(blob)
    arr = np.frombuffer(raw, dtype=np.dtype([("t", ">i4"), ("o", ">i4"), ("c", ">i4"),
                                             ("l", ">i4"), ("h", ">i4"), ("v", ">f4")]))
    idx = pd.Timestamp(day, tz="UTC") + pd.to_timedelta(arr["t"].astype(np.int64), unit="s")
    return pd.DataFrame({
        "Open": arr["o"] / scale, "High": arr["h"] / scale,
        "Low": arr["l"] / scale, "Close": arr["c"] / scale,
        "Volume": arr["v"].astype(float),
    }, index=idx)


def load_minutes(sym: str, scale: int) -> pd.DataFrame:
    bids, asks = [], []
    for d in trading_days():
        bids.append(decode(raw_path(sym, d, "BID"), d, scale))
        asks.append(decode(raw_path(sym, d, "ASK"), d, scale))
    bid = pd.concat([b for b in bids if not b.empty]).sort_index()
    ask = pd.concat([a for a in asks if not a.empty]).sort_index()
    bid = bid[~bid.index.duplicated()]
    ask = ask[~ask.index.duplicated()]
    bid["Spread"] = (ask["Close"] - bid["Close"]).reindex(bid.index)
    bid = bid[bid["Volume"] > 0]  # drop padded closed-market minutes
    bid.index.name = "Datetime"
    return bid


AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum", "Spread": "mean"}


def resample(m1: pd.DataFrame, rule: str) -> pd.DataFrame:
    return m1.resample(rule, label="left", closed="left").agg(AGG).dropna(subset=["Open"])


def resample_daily(m1: pd.DataFrame) -> pd.DataFrame:
    # Shift so 17:00 New York becomes midnight -> each bar = one broker trading day
    ny = m1.tz_convert("America/New_York")
    shifted = ny.copy()
    shifted.index = (ny.index + pd.Timedelta(hours=7)).tz_localize(None)
    d1 = shifted.resample("1D").agg(AGG).dropna(subset=["Open"])
    d1.index.name = "Date"
    return d1


def build() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, (sym, scale) in INSTRUMENTS.items():
        m1 = load_minutes(sym, scale)
        frames = {"1m": m1, **{tf: resample(m1, r) for tf, r in TIMEFRAMES.items()}, "1d": resample_daily(m1)}
        for tf, df in frames.items():
            if tf == "1m":
                df.to_csv(OUT_DIR / f"{name}_1m.csv.gz", compression="gzip")
                fname = f"{name}_1m.csv.gz"
            else:
                df.to_csv(OUT_DIR / f"{name}_{tf}.csv")
                fname = f"{name}_{tf}.csv"
            rows.append((name, tf, len(df), str(df.index[0])[:16], str(df.index[-1])[:16],
                         round(df["Spread"].median(), 3), fname))
    print(pd.DataFrame(rows, columns=["name", "tf", "bars", "first", "last", "median spread", "file"]).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="skip download, build from cache")
    args = ap.parse_args()
    if not args.build:
        ok = download_all()
        if not ok:
            print("Some files failed - re-run the script to retry them (cached files are skipped).")
            sys.exit(1)
    build()
