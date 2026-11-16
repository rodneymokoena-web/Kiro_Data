import contextlib, io, os
import swing_snap as SN, swings as S
SN.PLOT = False
with contextlib.redirect_stdout(io.StringIO()):
    d = SN.run()
v = os.environ.get("SWING_BUF", "2")
d.assign(source=S.DATA_SOURCE)[["source","entry_time","exit","r_net","entry_kind","risk_pts","stop_from"]].to_csv(f"output/buf_{S.DATA_SOURCE}_{v}.csv", index=False)
print("done", S.DATA_SOURCE, v, len(d))
