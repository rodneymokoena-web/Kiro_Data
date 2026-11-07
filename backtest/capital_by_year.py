import numpy as np, pandas as pd
O="output/"
def load(b,m):
    d=pd.read_csv(f"{O}us100_{b}_{m}_trades_2021_2026.csv"); d["entry_time"]=pd.to_datetime(d.entry_time,utc=True); return d[["entry_time","r_net"]]
rows=[]
for b in ("goatfunded","pepperstone"):
    sw,it=load(b,"swing"),load(b,"intraday")
    for m,d in (("Swing",sw),("Intraday",it),("Both",pd.concat([sw,it]))):
        d=d.sort_values("entry_time").reset_index(drop=True)
        eq=10000*np.cumprod(1+0.01*d.r_net.to_numpy()); d["cap"]=eq
        pk=np.maximum.accumulate(np.r_[10000,eq])[1:]; d["dd"]=(pk-eq)/pk
        start=10000
        for y,g in d.groupby(d.entry_time.dt.year):
            end=g.cap.iloc[-1]
            rows.append(dict(broker=b,model=m,year=y,trades=len(g),R=round(g.r_net.sum(),1),start=int(round(start)),end=int(round(end)),ret=round((end/start-1)*100,1)))
            start=end
x=pd.DataFrame(rows); x.to_csv(O+"us100_capital_by_year.csv",index=False)
for b in ("goatfunded","pepperstone"):
    for m in ("Swing","Intraday","Both"):
        g=x[(x.broker==b)&(x.model==m)]
        print(f"\n{b} - {m}"); print(g[["year","trades","R","start","end","ret"]].to_string(index=False))
