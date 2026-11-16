"""Swing target: opposite liquidity draw (4H / D / W / M swings) vs the current 1H swing low and 3R.
Usage: DATA_SOURCE=pepperstone TEST_START=2024-01-01 .venv/bin/python target_experiments.py
"""
import pandas as pd
import swing_snap as SN, swings as S
rows = []
def add(name, df):
    for r in df.itertuples(index=False):
        rows.append({"source": S.DATA_SOURCE, "variant": name, "entry_time": r.entry_time, "exit": r.exit, "r_net": r.r_net,
                     "planned_rr": r.planned_rr})
    print("done", name, len(df), flush=True)
add("current: 1H swing low", SN.run(target="1H swing low"))
add("3R", SN.run(target="3R"))
for p in (2, 5, 10):
    add(f"4H({p}) opposite liquidity", SN.run(target="liquidity", liq_tfs=("4H",), liq_pivot4=p))
add("4H(2) liquidity, at least 1R away", SN.run(target="liquidity", liq_tfs=("4H",), liq_pivot4=2, liq_min_rr=1.0))
add("4H(2) liquidity, at least 2R away", SN.run(target="liquidity", liq_tfs=("4H",), liq_pivot4=2, liq_min_rr=2.0))
add("4H(5) liquidity, at least 1R away", SN.run(target="liquidity", liq_tfs=("4H",), liq_pivot4=5, liq_min_rr=1.0))
add("D/W liquidity", SN.run(target="liquidity", liq_tfs=("D", "W")))
add("D/W/M liquidity", SN.run(target="liquidity", liq_tfs=("D", "W", "M")))
add("4H(2)+D/W/M liquidity (nearest)", SN.run(target="liquidity", liq_tfs=("4H", "D", "W", "M"), liq_pivot4=2))
pd.DataFrame(rows).to_csv(f"output/target_{S.DATA_SOURCE}.csv", index=False)
