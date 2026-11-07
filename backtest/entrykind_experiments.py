import contextlib, io
import pandas as pd
import swing_snap as SN, swings as S
SN.PLOT = False
with contextlib.redirect_stdout(io.StringIO()):
    d = SN.run()
suffix = "" if SN.ENTRY_KIND == "4h" else "_" + SN.BREAKER_BREAK + "_" + SN.BREAKER_FVG
name = "output/entrykind_" + S.DATA_SOURCE + "_" + SN.ENTRY_KIND + suffix + ".csv"
d.assign(source=S.DATA_SOURCE)[["source","entry_time","exit","r_net","entry_kind","risk_pts","stop_from"]].to_csv(name, index=False)
print("done", S.DATA_SOURCE, SN.ENTRY_KIND, SN.BREAKER_BREAK, SN.BREAKER_FVG, len(d), d.entry_kind.value_counts().to_dict() if len(d) else {})
