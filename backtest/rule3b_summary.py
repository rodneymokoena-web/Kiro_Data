"""Summarise output/{PFX}_*.csv -> output/{PFX}_summary.csv"""
import pandas as pd

import sys
PFX = sys.argv[1] if len(sys.argv) > 1 else "rule3b"
SRC = ["goat", "pepperstone", "goat_oos", "pepperstone_oos"]
df = pd.concat([pd.read_csv(f"output/{PFX}_{s}.csv") for s in SRC], ignore_index=True)
df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
df["period"] = df["source"].map(lambda s: "2021-23 unseen" if s.endswith("oos") else "2024-26")
df["broker"] = df["source"].str.replace("_oos", "")


def stats(g: pd.DataFrame) -> pd.Series:
    r = g.sort_values("entry_time")["r_net"]
    eq = r.cumsum()
    win, loss = r[r > 0].sum(), -r[r < 0].sum()
    return pd.Series({"trades": len(r), "win%": round((r > 0).mean() * 100, 0) if len(r) else 0,
                      "PF": round(win / loss, 2) if loss else float("inf"), "R": round(r.sum(), 1),
                      "maxDD_R": round((eq.cummax().clip(lower=0) - eq).max(), 1) if len(r) else 0})


rows = []
for (v, m, b), g in df.groupby(["variant", "model", "broker"]):
    s6 = stats(g)
    rows.append({"variant": v.split()[0], "model": m, "broker": b, **s6.to_dict(),
                 "R_2021_23": stats(g[g.period == "2021-23 unseen"])["R"], "R_2024_26": stats(g[g.period == "2024-26"])["R"],
                 "R_by_year": " ".join(f"{y}:{x:+.1f}" for y, x in g.groupby(g.entry_time.dt.year)["r_net"].sum().items())})
out = pd.DataFrame(rows).sort_values(["model", "broker", "variant"])
out.to_csv(f"output/{PFX}_summary.csv", index=False)
pd.set_option("display.width", 250)
print(out.to_string(index=False))
print()
print({k.split()[0]: k for k in df["variant"].unique()})
