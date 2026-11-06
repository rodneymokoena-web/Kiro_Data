import numpy as np, pandas as pd
def st(r):
    r=r.reset_index(drop=True)
    if len(r)==0: return dict(n=0,PF=np.nan,R=0,acct=10000,dd=0)
    c=np.r_[10000,10000*np.cumprod(1+0.01*r.to_numpy())]; p=np.maximum.accumulate(c)
    w,l=r[r>0].sum(),-r[r<0].sum()
    return dict(n=len(r),PF=round(w/l,2) if l else np.inf,R=round(r.sum(),1),acct=int(c[-1]),dd=round(((p-c)/p).max()*100,1))
out=[]
for b,(a,o) in {"GoatFunded":("goat","goat_oos"),"Pepperstone":("pepperstone","pepperstone_oos")}.items():
    d=pd.concat([pd.read_csv(f"output/bias_{s}.csv") for s in (o,a)]); d["entry_time"]=pd.to_datetime(d.entry_time,utc=True)
    for (v,m),g in d.groupby(["variant","model"]):
        g=g.sort_values("entry_time"); out.append({"broker":b,"variant":v,"model":m,**st(g.r_net)})
    for v,g in d.groupby("variant"):
        g=g.sort_values("entry_time"); out.append({"broker":b,"variant":v,"model":"both",**st(g.r_net)})
x=pd.DataFrame(out); x.to_csv("output/bias_summary.csv",index=False)
print(x.to_string(index=False))
