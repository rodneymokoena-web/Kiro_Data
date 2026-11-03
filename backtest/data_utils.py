"""Shared data-cleaning helpers."""
from __future__ import annotations

import pandas as pd

SPIKE_MULT = 10  # a jump this many times the typical bar range is treated as a bad tick


def clean_bad_ticks(df: pd.DataFrame, verbose: str | None = None) -> pd.DataFrame:
    """Fix single-bar bad prints where the Open (or a wick) jumps far away from both
    neighbouring bars and immediately snaps back. Real gaps (after session breaks) are kept
    because the following bar does not return to the previous price."""
    df = df.copy()
    rng = (df["High"] - df["Low"]).rolling(100, min_periods=20).median().bfill()
    prev_c, next_o = df["Close"].shift(1), df["Open"].shift(-1)
    tol = SPIKE_MULT * rng
    # never touch the first bar after a session break / weekend: real gaps happen there
    idx = df.index.to_series()
    same_session = (idx.diff() < pd.Timedelta(hours=2)) & (idx.diff(-1).abs() < pd.Timedelta(hours=2))
    tol = tol.where(same_session, float("inf"))
    fixed = []

    # 1) bad Open: far from previous close, while the close / next open stay near the previous close
    bad_open = ((df["Open"] - prev_c).abs() > tol) & ((df["Close"] - prev_c).abs() < tol)
    for t in df.index[bad_open]:
        old = df.at[t, "Open"]
        df.at[t, "Open"] = prev_c[t]
        body_hi, body_lo = max(df.at[t, "Open"], df.at[t, "Close"]), min(df.at[t, "Open"], df.at[t, "Close"])
        if df.at[t, "High"] == old:
            df.at[t, "High"] = body_hi
        if df.at[t, "Low"] == old:
            df.at[t, "Low"] = body_lo
        fixed.append((t, "open", old, df.at[t, "Open"]))

    # 2) bad wick: High/Low far beyond both neighbours' prices
    ref_hi = pd.concat([prev_c, next_o, df["Open"], df["Close"]], axis=1).max(axis=1)
    ref_lo = pd.concat([prev_c, next_o, df["Open"], df["Close"]], axis=1).min(axis=1)
    for t in df.index[(df["High"] - ref_hi) > tol]:
        fixed.append((t, "high", df.at[t, "High"], ref_hi[t]))
        df.at[t, "High"] = ref_hi[t]
    for t in df.index[(ref_lo - df["Low"]) > tol]:
        fixed.append((t, "low", df.at[t, "Low"], ref_lo[t]))
        df.at[t, "Low"] = ref_lo[t]

    if verbose:
        for t, field, old, new in fixed:
            print(f"  [clean] {verbose} {t} {field}: {old} -> {new}")
    return df
