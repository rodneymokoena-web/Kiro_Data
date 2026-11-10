"""Write an MT5 Strategy Tester style journal (.log) from a Python backtest trade list.

Usage (from the backtest folder):
    .venv/bin/python mt5_tester_log.py output/snap_exness_oct26.csv output/mt5_tester_intraday_exness_202610.log

The log is a REPLAY of the Python intraday backtest in the MetaTrader 5 tester journal format - it was NOT produced by
MetaTrader (the MT5 EA only trades the swing model). Each trade: limit order placed at the reversal candle close,
triggered / deal performed at the fill, stop moved to breakeven at +1R (re-simulated on the same 5m candles as the
backtest), closed by stop loss / take profit. Volume = RISK_PCT of the running balance / risk in points (1 lot = 1 USD per
point, Exness US100 contract), rounded down to 0.01 lot; profit includes the round-trip spread cost of the backtest.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

SRC, OUT = sys.argv[1], sys.argv[2]
DEPOSIT = float(os.environ.get("DEPOSIT", "10000"))
RISK_PCT = float(os.environ.get("RISK_PCT", "1.0"))
SYMBOL = "US100"
SOURCE = os.environ.get("DATA_SOURCE", "exness")
EXPERT = "ICT_Intraday_Snap"
COST = json.loads(Path(f"data/{SOURCE}/costs.json").read_text())[SYMBOL]
BE_AT_R = 1.0

t = pd.read_csv(SRC, parse_dates=["reversal_time", "entry_time", "exit_time", "sweep_time"])
t = t[t.entry_time.notna()].sort_values(["entry_time", "reversal_time"]).reset_index(drop=True)
bars = pd.read_csv(f"data/{SOURCE}/{SYMBOL}_5m.csv", parse_dates=["Datetime"], index_col="Datetime")
bars = bars[(bars.index >= t.reversal_time.min() - pd.Timedelta(days=1)) & (bars.index <= t.exit_time.max() + pd.Timedelta(days=1))]
H, L, C, SP = bars.High.to_numpy(), bars.Low.to_numpy(), bars.Close.to_numpy(), bars.Spread.to_numpy()
IDX = bars.index


def mt(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y.%m.%d %H:%M:%S")


def px(x: float) -> str:
    return f"{x:.2f}"


def resim(r) -> tuple[pd.Timestamp | None, str, pd.Timestamp]:
    """Same rules as backtest.simulate on the 5m candles: returns (breakeven time, exit kind, exit candle time)."""
    short = r.signal == "short"
    q = IDX.searchsorted(r.entry_time)
    risk = abs(r.entry_price - r.stop)
    stop, be_t = r.stop, None
    for k in range(q, len(IDX)):
        if (H[k] >= stop) if short else (L[k] <= stop):
            return be_t, ("breakeven" if be_t is not None else "stop"), IDX[k]
        if k > q and ((L[k] <= r.target) if short else (H[k] >= r.target)):
            return be_t, "target", IDX[k]
        if be_t is None and k > q and ((L[k] <= r.entry_price - BE_AT_R * risk) if short else (H[k] >= r.entry_price + BE_AT_R * risk)):
            stop, be_t = r.entry_price, IDX[k]
    return be_t, "open", IDX[-1]


# ---- build the events (simulated time, order, text) ------------------------------------------------------------------
events, balance, mism = [], DEPOSIT, 0
ticket = 1
trades = []
for r in t.itertuples(index=False):
    be_t, kind, ex_t = resim(r)
    if kind != r.exit or ex_t != r.exit_time:
        mism += 1
    trades.append((r, be_t, kind))

# volume needs the balance at the fill -> walk the trades in fill order, closing earlier exits first
open_q, rows = [], []
for r, be_t, kind in trades:
    rows.append({"r": r, "be_t": be_t, "kind": kind})
# balance at fill = deposit + profit of trades closed before the fill
done_profit = []
for row in rows:
    r = row["r"]
    bal = DEPOSIT + sum(p for (xt, p) in done_profit if xt <= r.entry_time)
    vol = max(math.floor(bal * RISK_PCT / 100 / r.risk_pts * 100) / 100, 0.01)
    gross = (r.exit_price - r.entry_price) * (-1 if r.signal == "short" else 1) * vol
    profit = round(gross - COST * vol, 2)
    row.update(vol=vol, profit=profit, bal_fill=bal)
    done_profit.append((r.exit_time, profit))

for row in rows:
    r, vol = row["r"], row["vol"]
    short = r.signal == "short"
    oside, side, cside = ("sell limit", "sell", "buy") if short else ("buy limit", "buy", "sell")
    place_t = r.reversal_time + pd.Timedelta(minutes=5)              # reversal candle close
    k = IDX.searchsorted(r.reversal_time)
    bid = C[k] if k < len(C) else r.entry_price
    ask = bid + (SP[k] if k < len(SP) else COST)
    o_tk, d_tk, c_tk = ticket, ticket + 1, ticket + 2
    ticket += 3
    sl, tp = px(r.stop), px(r.target)
    info = (f"{'SHORT' if short else 'LONG'} signal: {r.swept} swept {mt(r.sweep_time)} | {r.ifvg_tf} IFVG + "
            f"{r.bos_kind} @ {px(r.bos_level)} | entry {r.entry_zone} {px(r.entry_price)} risk {r.risk_pts:.2f} pts | "
            f"balance {row['bal_fill']:.2f}")
    ev = [
        (place_t, 0, "EXP", info),
        (place_t, 1, "TRD", f"{oside} {vol:.2f} {SYMBOL} at {px(r.entry_price)} sl: {sl} tp: {tp} ({px(bid)} / {px(ask)})"),
        (place_t, 2, "TRD", f"CTrade::OrderSend: {oside} {vol:.2f} {SYMBOL} at {px(r.entry_price)} sl: {sl} tp: {tp} [done]"),
        (r.entry_time, 3, "TRD", f"order [#{o_tk} {oside} {vol:.2f} {SYMBOL} at {px(r.entry_price)}] triggered"),
        (r.entry_time, 4, "TRD", f"deal #{d_tk} {side} {vol:.2f} {SYMBOL} at {px(r.entry_price)} done (based on order #{o_tk})"),
        (r.entry_time, 5, "TRD", f"deal performed [#{d_tk} {side} {vol:.2f} {SYMBOL} at {px(r.entry_price)}]"),
        (r.entry_time, 6, "TRD", f"order performed {side} {vol:.2f} at {px(r.entry_price)} [#{o_tk} {oside} {vol:.2f} {SYMBOL} at {px(r.entry_price)}]"),
    ]
    cur_sl = sl
    if row["be_t"] is not None:
        cur_sl = px(r.entry_price)
        ev += [(row["be_t"], 7, "EXP", f"breakeven: +{BE_AT_R:g}R reached, stop -> entry #{o_tk}"),
               (row["be_t"], 8, "TRD", f"position modified [#{o_tk} {side} {vol:.2f} {SYMBOL} {px(r.entry_price)} sl: {cur_sl} tp: {tp}]")]
    trig = "take profit" if r.exit == "target" else "stop loss"
    ev += [
        (r.exit_time, 9, "TRD", f"{trig} triggered #{o_tk} {side} {vol:.2f} {SYMBOL} {px(r.entry_price)} sl: {cur_sl} tp: {tp} [#{c_tk} {cside} {vol:.2f} {SYMBOL} at {px(r.exit_price)}]"),
        (r.exit_time, 10, "TRD", f"deal #{c_tk + 0} {cside} {vol:.2f} {SYMBOL} at {px(r.exit_price)} done (based on order #{c_tk})"),
        (r.exit_time, 11, "TRD", f"deal performed [#{c_tk} {cside} {vol:.2f} {SYMBOL} at {px(r.exit_price)}]"),
        (r.exit_time, 12, "TRD", f"order performed {cside} {vol:.2f} at {px(r.exit_price)} [#{c_tk} {cside} {vol:.2f} {SYMBOL} at {px(r.exit_price)}]"),
        (r.exit_time, 13, "EXP", f"closed #{o_tk} {r.exit.upper()} profit {row['profit']:+.2f} USD (spread {COST:g} pts) | {r.r_net:+.2f}R net"),
    ]
    events += [(a, b, o_tk, c, d) for (a, b, c, d) in ev]

events.sort(key=lambda e: (e[0], e[2] if e[1] < 9 else -1, e[1]))  # same candle: exits of older trades first

# ---- write the journal -------------------------------------------------------------------------------------------------
start = pd.Timestamp(t.reversal_time.min()).normalize().replace(day=1)
end = pd.Timestamp(t.exit_time.max()).normalize() + pd.Timedelta(days=1)
final = DEPOSIT + sum(r["profit"] for r in rows)
wall = datetime(2026, 11, 1, 12, 0, 0)
lines = []


def put(code: str, src: str, msg: str, sim=None, ms: int = 7):
    global wall
    wall += timedelta(milliseconds=ms)
    stamp = wall.strftime("%H:%M:%S.") + f"{wall.microsecond // 1000:03d}"
    lines.append(f"{code}\t0\t{stamp}\t{src}\t" + (f"{mt(sim)}   {msg}" if sim is not None else msg))


put("KS", "Tester", "NOTE: replay of the Python intraday backtest (intraday_snap.py) in MT5 tester journal format - not generated by MetaTrader")
put("KS", "Tester", f"source {SRC} | data {SOURCE} {SYMBOL} 5m | {len(rows)} trades | risk {RISK_PCT:g}% per trade | 1 lot = 1 USD per point")
put("CS", "Tester", f"expert file added: Experts\\{EXPERT}.ex5.")
put("CS", "Tester", f"initial deposit {DEPOSIT:.2f} USD, leverage 1:200")
put("CS", "Tester", "successfully initialized")
put("CS", "Symbols", f"{SYMBOL}: symbol to be synchronized")
put("CS", "Symbols", f"{SYMBOL}: history synchronized from {(start - pd.Timedelta(days=365)).strftime('%Y.%m.%d')} to {end.strftime('%Y.%m.%d')}")
put("CS", "Tester", f"{SYMBOL},M5 (Exness-MT5Real): 1 minute OHLC ticks generating")
put("CS", "Tester", f"{SYMBOL},M5: testing of Experts\\{EXPERT}.ex5 from {start.strftime('%Y.%m.%d %H:%M')} to {end.strftime('%Y.%m.%d %H:%M')} started")
put("CS", f"{EXPERT} ({SYMBOL},M5)", "inputs: bias filter=true, IFVG 5m/15m, BOS close or wick + post-sweep MSS, reversal 48 candles, entry valid 60 min, target 3R, breakeven +1R, macro liquidity=true, "
    f"min stop {os.environ.get('MIN_STOP_PTS', '15')} pts, one trade per entry={os.environ.get('ONE_PER_ENTRY', '1') == '1'}", sim=start)
for (sim, _o, _tk, kind, msg) in events:
    put("KS" if kind == "TRD" else "CS", "Trade" if kind == "TRD" else f"{EXPERT} ({SYMBOL},M5)", msg, sim=sim, ms=3)
wins = sum(1 for r in rows if r["profit"] > 0)
put("CS", f"{EXPERT} ({SYMBOL},M5)", f"summary: {len(rows)} trades, {wins} profitable, net {final - DEPOSIT:+.2f} USD, {t.r_net.sum():+.2f}R", sim=end)
put("CS", "Tester", f"final balance {final:.2f} USD")
put("CS", "Tester", f"{SYMBOL},M5: test passed")
put("CS", "Tester", "removed 0 orders, 0 positions")
Path(OUT).write_text("\n".join(lines) + "\n")
print(f"{OUT}: {len(lines)} lines, {len(rows)} trades, final balance {final:.2f} ({final - DEPOSIT:+.2f}), "
      f"re-simulation mismatches {mism}")
