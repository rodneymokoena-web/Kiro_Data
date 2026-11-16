import numpy as np, pandas as pd
def st(r):
    r=r.reset_index(drop=True)
    c=np.r_[10000,10000*np.cumprod(1+0.01*r.to_numpy())]; p=np.maximum.accumulate(c)
    w,l=r[r>0].sum(),-r[r<0].sum()
    return dict(n=len(r),WR=round((r>0.2).mean()*100),PF=round(w/l,2) if l else np.inf,R=round(r.sum(),1),acct=int(c[-1]),dd=round(((p-c)/p).max()*100,1))
out=[]
for b,(a,o) in {"GoatFunded":("goat","goat_oos"),"Pepperstone":("pepperstone","pepperstone_oos")}.items():
    d=pd.concat([pd.read_csv(f"output/fvgliq_{s}_{f}.csv") for s in (o,a) for f in (0,1)]); d["entry_time"]=pd.to_datetime(d.entry_time,utc=True)
    for f in (0,1):
        x=d[d.fvg_liq==f]
        for m in ("swing","intraday"):
            g=x[x.model==m].sort_values("entry_time"); out.append({"broker":b,"fvg_liq":f,"model":m,**st(g.r_net)})
        g=x.sort_values("entry_time"); out.append({"broker":b,"fvg_liq":f,"model":"both",**st(g.r_net)})
    # swing, split by period
    for f in (0,1):
        g=d[(d.fvg_liq==f)&(d.model=="swing")]; 
        for nm,msk in (("2021-23",g.entry_time<"2024-01-01"),("2024-26",g.entry_time>="2024-01-01")):
            out.append({"broker":b,"fvg_liq":f,"model":"swing "+nm,**st(g[msk].sort_values("entry_time").r_net)})
x=pd.DataFrame(out); x.to_csv("output/fvgliq_summary.csv",index=False); print(x.to_string(index=False))
