import contextlib, io, os
import pandas as pd
import swing_snap as SN, swings as S
SN.PLOT = False
with contextlib.redirect_stdout(io.StringIO()):
    d = SN.run()
v = os.environ.get("OB_FALLBACK", "prev").split()[0]
d.assign(source=S.DATA_SOURCE)[["source","entry_time","exit","r_net","entry_kind","risk_pts","stop_from"]].to_csv(f"output/obfb_{S.DATA_SOURCE}_{v}.csv", index=False)
print("done", S.DATA_SOURCE, v, len(d), d.stop_from.value_counts().to_dict())
