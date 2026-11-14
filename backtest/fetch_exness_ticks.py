"""Download Exness US Tech 100 (USTEC) tick history and convert it to compact monthly files.

Usage:
    [EXNESS_SYMBOL=XAUUSD] .venv/bin/python fetch_exness_ticks.py [first YYYY-MM] [last YYYY-MM]   (default USTEC, 2021-04 .. 2026-10)
Source: https://ticks.ex2archive.com/ticks/USTEC/{YYYY}/{MM}/Exness_USTEC_{YYYY}_{MM}.zip (public archive, UTC, bid/ask).
Writes data/exness_ticks/USTEC_{YYYY}_{MM}.npz with t (int64 ms since epoch, UTC), bid, ask (float64).
"""
from __future__ import annotations

import io
import os
import sys
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "data" / "exness_ticks"
SYM = os.environ.get("EXNESS_SYMBOL", "USTEC")          # USTEC (US Tech 100) | XAUUSD
URL = "https://ticks.ex2archive.com/ticks/{s}/{y}/{m:02d}/Exness_{s}_{y}_{m:02d}.zip"


def fetch(y: int, m: int) -> str:
    dst = OUT / f"{SYM}_{y}_{m:02d}.npz"
    if dst.exists():
        return f"{y}-{m:02d} cached"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(URL.format(s=SYM, y=y, m=m), timeout=180) as r:
                blob = r.read()
            break
        except Exception as e:                      # noqa: BLE001 - retry any network error
            if attempt == 4:
                return f"{y}-{m:02d} FAILED {e}"
            time.sleep(10 * (attempt + 1))
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        with z.open(z.namelist()[0]) as f:
            df = pd.read_csv(f, usecols=["Timestamp", "Bid", "Ask"])
    t = pd.to_datetime(df["Timestamp"], utc=True, format="ISO8601").dt.as_unit("ms").astype("int64")   # ms since epoch
    np.savez(dst, t=t.to_numpy(), bid=df["Bid"].to_numpy(float), ask=df["Ask"].to_numpy(float))
    return f"{y}-{m:02d} {len(df):,} ticks"


def main() -> None:
    first = pd.Period(sys.argv[1] if len(sys.argv) > 1 else "2021-04", "M")
    last = pd.Period(sys.argv[2] if len(sys.argv) > 2 else "2026-10", "M")
    OUT.mkdir(parents=True, exist_ok=True)
    months = pd.period_range(first, last, freq="M")
    with ThreadPoolExecutor(4) as ex:
        for msg in ex.map(lambda p: fetch(p.year, p.month), months):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
