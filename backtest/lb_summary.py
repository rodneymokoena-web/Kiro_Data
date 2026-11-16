import numpy as np, pandas as pd
def st(r):
    r=r.reset_index(drop=True)
    c=np.r_[10000,10000*np.cumprod(1+0.01*r.to_numpy())]; p=np.maximum.accumulate(c)
    w,l=r[r>0].sum(),-r[r<0].sum()
    return dict(n=len(r),WR=round((r>0.2).mean()*100),PF=round(w/l,2),R=round(r.sum(),1),acct=int(c[-1]),dd=round(((p-c)/p).max()*100,1))
out=[]
for b,(a,o) in {"GoatFunded":("goat","goat_oos"),"Pepperstone":("pepperstone","pepperstone_oos")}.items():
    for lb in (60,20,10):
        d=pd.concat([pd.read_csv(f"output/lb_{s}_{lb}.csv") for s in (o,a)]); d["entry_time"]=pd.to_datetime(d.entry_time,utc=True); d=d.sort_values("entry_time")
        out.append({"broker":b,"lookback":lb,"period":"2021-26",**st(d.r_net)})
        for nm,k in (("21-23",d.entry_time<"2024-01-01"),("24-26",d.entry_time>="2024-01-01")):
            out.append({"broker":b,"lookback":lb,"period":nm,**st(d[k].r_net)})
x=pd.DataFrame(out); x.to_csv("output/lb_summary.csv",index=False); print(x.to_string(index=False))
