import numpy as np, pandas as pd
def st(r):
    r=r.reset_index(drop=True)
    if not len(r): return {}
    c=np.r_[10000,10000*np.cumprod(1+0.01*r.to_numpy())]; p=np.maximum.accumulate(c)
    w,l=r[r>0].sum(),-r[r<0].sum()
    return dict(n=len(r),WR=round((r>0.2).mean()*100),PF=round(w/l,2) if l else np.inf,R=round(r.sum(),1),acct=int(c[-1]),dd=round(((p-c)/p).max()*100,1))
names={"4h":"4H IFVG entry (current)"}
for k in ("breaker","either"):
    for br,fv in (("close","first"),("wick","first"),("close","any"),("wick","any")):
        names[f"{k}_{br}_{fv}"]=f"{k}: break by {br}, FVG {'right after' if fv=='first' else 'anywhere after'}"
out=[]; extra=[]
for b,(a,o) in {"GoatFunded":("goat","goat_oos"),"Pepperstone":("pepperstone","pepperstone_oos")}.items():
    for v,nm in names.items():
        d=pd.concat([pd.read_csv(f"output/entrykind_{s}_{v}.csv") for s in (o,a)]); d["entry_time"]=pd.to_datetime(d.entry_time,utc=True); d=d.sort_values("entry_time")
        out.append({"broker":b,"variant":nm,"period":"2021-26",**st(d.r_net)})
        for pn,k in (("21-23",d.entry_time<"2024-01-01"),("24-26",d.entry_time>="2024-01-01")):
            out.append({"broker":b,"variant":nm,"period":pn,**st(d[k].r_net)})
        if v.startswith("either"):
            g=d[d.entry_kind=="1H breaker FVG"]; extra.append({"broker":b,"variant":nm,"breaker_trades":len(g),**{("br_"+k):v2 for k,v2 in st(g.r_net).items() if k in ("PF","R")}})
x=pd.DataFrame(out); x.to_csv("output/entrykind_summary.csv",index=False)
print(x[x.period=="2021-26"].to_string(index=False)); print(pd.DataFrame(extra).to_string(index=False))
