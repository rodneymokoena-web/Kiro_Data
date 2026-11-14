import numpy as np, pandas as pd
def st(r):
    r=r.reset_index(drop=True)
    c=np.r_[10000,10000*np.cumprod(1+0.01*r.to_numpy())]; p=np.maximum.accumulate(c)
    w,l=r[r>0].sum(),-r[r<0].sum()
    return dict(n=len(r),PF=round(w/l,2),R=round(r.sum(),1),acct=int(c[-1]),dd=round(((p-c)/p).max()*100,1))
V={"off":"0","all FVGs":"1all","intact (no 4H close through)":"1intact","fresh (never traded into)":"1fresh"}
import os
out=[]
for b,(a,o) in {"GoatFunded":("goat","goat_oos"),"Pepperstone":("pepperstone","pepperstone_oos")}.items():
    for v,suf in V.items():
        fs=[]
        for s in (o,a):
            f=f"output/fvgliq_{s}_{suf}.csv"
            if not os.path.exists(f) and suf=="1all": f=f"output/fvgliq_{s}_1.csv"
            fs.append(pd.read_csv(f))
        d=pd.concat(fs); d["entry_time"]=pd.to_datetime(d.entry_time,utc=True)
        for m in ("swing","both"):
            g=(d if m=="both" else d[d.model==m]).sort_values("entry_time")
            out.append({"broker":b,"variant":v,"model":m,**st(g.r_net)})
        g=d[d.model=="swing"]
        for nm,k in (("21-23",g.entry_time<"2024-01-01"),("24-26",g.entry_time>="2024-01-01")):
            out.append({"broker":b,"variant":v,"model":"swing "+nm,**st(g[k].sort_values("entry_time").r_net)})
x=pd.DataFrame(out); x.to_csv("output/fvgliq_summary2.csv",index=False); print(x.to_string(index=False))
