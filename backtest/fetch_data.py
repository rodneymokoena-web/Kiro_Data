"""Download historical OHLCV data from Yahoo Finance and save to CSV.

Usage:
    .venv/bin/python fetch_data.py

Yahoo proxies:
    US Tech 100 -> NQ=F  (Nasdaq-100 E-mini futures, ~23h/day like a CFD)
                   ^NDX  (Nasdaq-100 cash index, regular US session only)
    XAUUSD      -> GC=F  (COMEX gold futures, tracks spot closely)
"""
from pathlib import Path

import pandas as pd
import yfinance as yf

from data_utils import clean_bad_ticks

START = "2026-01-01"
END = None  # None = up to today

SYMBOLS = {
    "US100_NQF": "NQ=F",
    "US100_NDX": "^NDX",
    "XAUUSD_GCF": "GC=F",
}

# yfinance limits: 1d unlimited, 1h ~730 days back, <=30m only ~60 days back
INTERVALS = ["1d", "1h", "15m", "5m"]
INTRADAY_LIMIT_DAYS = {"15m": 59, "5m": 59}
# Extra 1h history so D/W/M swings already exist at the start of the test period
EXTENDED_1H_START = "2025-01-02"

DATA_DIR = Path(__file__).parent / "data"


def effective_start(interval: str) -> str:
    """Clamp the start date to Yahoo's look-back limit for short intervals."""
    limit = INTRADAY_LIMIT_DAYS.get(interval)
    if limit is None:
        return START
    earliest = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=limit))
    return max(pd.Timestamp(START, tz="UTC"), earliest).strftime("%Y-%m-%d")


def fetch(ticker: str, interval: str, start: str | None = None) -> pd.DataFrame:
    df = yf.download(
        ticker,
        start=start or effective_start(interval),
        end=END,
        interval=interval,
        auto_adjust=False,
        progress=False,
        multi_level_index=False,
    )
    if df.empty:
        return df
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    # Normalise timestamps to UTC
    idx = pd.to_datetime(df.index)
    df.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    df.index.name = "Datetime"
    return clean_bad_ticks(df, verbose=f"{ticker} {interval}")


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    rows = []
    for name, ticker in SYMBOLS.items():
        for interval in INTERVALS:
            df = fetch(ticker, interval)
            path = DATA_DIR / f"{name}_{interval}.csv"
            if df.empty:
                rows.append((name, ticker, interval, 0, "-", "-", "NO DATA"))
                continue
            df.to_csv(path)
            rows.append((name, ticker, interval, len(df),
                         df.index[0].strftime("%Y-%m-%d %H:%M"),
                         df.index[-1].strftime("%Y-%m-%d %H:%M"), path.name))

    # Extended 1h history (used by swings.py to build D/W/M candles)
    for name, ticker in SYMBOLS.items():
        if name == "US100_NDX":
            continue
        df = fetch(ticker, "1h", start=EXTENDED_1H_START)
        path = DATA_DIR / f"{name}_1h_ext.csv"
        df.to_csv(path)
        rows.append((name, ticker, "1h ext", len(df), df.index[0].strftime("%Y-%m-%d %H:%M"),
                     df.index[-1].strftime("%Y-%m-%d %H:%M"), path.name))

    summary = pd.DataFrame(rows, columns=["name", "ticker", "interval", "bars",
                                          "first (UTC)", "last (UTC)", "file"])
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
