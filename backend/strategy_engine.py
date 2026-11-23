"""Deterministic, candle-close strategy signals for TradeX AI paper trading."""
from __future__ import annotations
from math import sqrt

def _ema(x, n):
    if len(x) < n: return None
    a=sum(x[:n])/n; k=2/(n+1)
    for v in x[n:]: a=v*k+a*(1-k)
    return a

def _sma(x,n):
    return sum(x[-n:])/n if len(x)>=n else None

def _rsi(x,n=14):
    if len(x)<n+1:return None
    ds=[x[i]-x[i-1] for i in range(1,len(x))]
    gains=sum(max(v,0) for v in ds[-n:])/n
    losses=sum(max(-v,0) for v in ds[-n:])/n
    if losses==0:return 100.0
    rs=gains/losses
    return 100-100/(1+rs)

def _atr(c,n=14):
    if len(c)<n+1:return None
    tr=[]
    for i in range(1,len(c)):
        p=c[i-1]["close"]; b=c[i]
        tr.append(max(b["high"]-b["low"],abs(b["high"]-p),abs(b["low"]-p)))
    return sum(tr[-n:])/n

def _macd(x):
    if len(x)<35:return None
    line=_ema(x,12)-_ema(x,26)
    hist=[]
    for i in range(26,len(x)+1):
        a=_ema(x[:i],12); b=_ema(x[:i],26)
        if a is not None and b is not None: hist.append(a-b)
    sig=_ema(hist,9)
    return line,sig

def _bands(x,n=20,m=2):
    if len(x)<n:return None
    a=x[-n:]; mean=sum(a)/n; sd=sqrt(sum((v-mean)**2 for v in a)/n)
    return mean-m*sd,mean+m*sd,mean,sd

def _adx(c,n=14):
    if len(c)<n*2+1:return None
    plus=[];minus=[];trs=[]
    for i in range(1,len(c)):
        a,b=c[i-1],c[i]
        up=b["high"]-a["high"]; down=a["low"]-b["low"]
        plus.append(up if up>down and up>0 else 0)
        minus.append(down if down>up and down>0 else 0)
        trs.append(max(b["high"]-b["low"],abs(b["high"]-a["close"]),abs(b["low"]-a["close"])))
    tr=sum(trs[-n:])/n
    if tr<=0:return None
    pdi=100*(sum(plus[-n:])/n)/tr; mdi=100*(sum(minus[-n:])/n)/tr
    dx=100*abs(pdi-mdi)/max(pdi+mdi,1e-12)
    return dx,pdi,mdi

def _stoch(c,n=14):
    if len(c)<n+3:return None
    def k_at(end):
        w=c[end-n:end]; lo=min(v["low"] for v in w); hi=max(v["high"] for v in w)
        return 50 if hi==lo else 100*(c[end-1]["close"]-lo)/(hi-lo)
    ks=[k_at(i) for i in range(len(c)-2,len(c)+1)]
    return ks[-1],sum(ks)/len(ks),ks[-2],sum(ks[:-1])/max(len(ks)-1,1)

def _cci(c,n=20):
    if len(c)<n:return None
    tp=[(v["high"]+v["low"]+v["close"])/3 for v in c[-n:]]
    mean=sum(tp)/n; dev=sum(abs(v-mean) for v in tp)/n
    return 0 if dev==0 else (tp[-1]-mean)/(0.015*dev)

def _willr(c,n=14):
    if len(c)<n:return None
    w=c[-n:]; hi=max(v["high"] for v in w); lo=min(v["low"] for v in w)
    return 0 if hi==lo else -100*(hi-c[-1]["close"])/(hi-lo)

def _vwap(c,n=20):
    w=c[-n:]; vol=sum(max(float(v.get("volume",0)),0) for v in w)
    if vol<=0:return None
    return sum(((v["high"]+v["low"]+v["close"])/3)*max(float(v.get("volume",0)),0) for v in w)/vol

def _obv(c):
    if len(c)<22:return None
    vals=[0.0]
    for a,b in zip(c[:-1],c[1:]):
        vals.append(vals[-1]+(float(b.get("volume",0)) if b["close"]>a["close"] else -float(b.get("volume",0)) if b["close"]<a["close"] else 0))
    return vals[-1]-vals[-6]

def _signal_cross(prev_a,prev_b,a,b):
    if None in (prev_a,prev_b,a,b):return None
    if prev_a<=prev_b and a> b:return "BUY"
    if prev_a>=prev_b and a< b:return "SELL"
    return None

def signal_for(strategy_id:str,candles:list[dict])->str|None:
    """Return BUY/SELL only on a confirmed closed-candle signal; otherwise None."""
    c=candles; x=[float(v["close"]) for v in c]
    if len(c)<25:return None
    p=x[-2]; q=x[-1]; prev=x[:-1]
    if strategy_id=="STR-001":
        return _signal_cross(_ema(prev,9),_ema(prev,21),_ema(x,9),_ema(x,21))
    if strategy_id=="STR-002":
        return _signal_cross(_sma(prev,10),_sma(prev,30),_sma(x,10),_sma(x,30))
    if strategy_id=="STR-003":
        a,b,d=_ema(x,9),_ema(x,21),_ema(x,50)
        ap,bp,dp=_ema(prev,9),_ema(prev,21),_ema(prev,50)
        return "BUY" if (ap<=bp or bp<=dp) and a>b>d else "SELL" if (ap>=bp or bp>=dp) and a<b<d else None
    if strategy_id in ("STR-004","STR-005"):
        m=_macd(x); mp=_macd(prev)
        if not m or not mp:return None
        if strategy_id=="STR-004":return _signal_cross(mp[0],mp[1],m[0],m[1])
        return _signal_cross(mp[0],0,m[0],0)
    if strategy_id in ("STR-006","STR-048","STR-053","STR-057"):
        ad=_adx(c)
        if not ad:return None
        dx,plus,minus=ad
        if strategy_id=="STR-006" or strategy_id=="STR-053" or strategy_id=="STR-057":
            if dx<20:return None
        if strategy_id=="STR-048":
            old=_adx(c[:-1])
            if not old:return None
            return _signal_cross(old[1],old[2],plus,minus)
        if strategy_id=="STR-053":
            m=_macd(x)
            return ("BUY" if m and m[0]>m[1] and plus>minus else "SELL" if m and m[0]<m[1] and minus>plus else None)
        if strategy_id=="STR-057":
            hi=max(v["high"] for v in c[-21:-1]);lo=min(v["low"] for v in c[-21:-1])
            return "BUY" if q>hi and plus>minus else "SELL" if q<lo and minus>plus else None
        return "BUY" if plus>minus else "SELL" if minus>plus else None
    if strategy_id in ("STR-007","STR-054","STR-026"):
        a=_atr(c)
        if not a:return None
        mid=(c[-1]["high"]+c[-1]["low"])/2
        trend="BUY" if q>mid-a*2 else "SELL" if q<mid+a*2 else None
        oldmid=(c[-2]["high"]+c[-2]["low"])/2
        old="BUY" if p>oldmid-a*2 else "SELL" if p<oldmid+a*2 else None
        if strategy_id=="STR-054":
            r=_rsi(x);return trend if trend!=old and r is not None and ((trend=="BUY" and r>50) or (trend=="SELL" and r<50)) else None
        return trend if trend!=old else None
    if strategy_id in ("STR-010","STR-050"):
        n=20 if strategy_id=="STR-010" else 10
        hi=max(v["high"] for v in c[-n-1:-1]);lo=min(v["low"] for v in c[-n-1:-1])
        return "BUY" if q>hi else "SELL" if q<lo else None
    if strategy_id in ("STR-011","STR-056"):
        b=_bands(x)
        if not b:return None
        lo,hi,_,_=b
        if strategy_id=="STR-011":
            old=_bands(prev)
            if not old:return None
            return "BUY" if p<old[0] and q>lo else "SELL" if p>old[1] and q<hi else None
        r=_rsi(x)
        return "BUY" if q<lo and r is not None and r<35 else "SELL" if q>hi and r is not None and r>65 else None
    if strategy_id=="STR-012":
        b=_bands(x); old=_bands(prev)
        if not b or not old:return None
        width=(b[1]-b[0])/max(b[2],1e-12); oldwidth=(old[1]-old[0])/max(old[2],1e-12)
        return "BUY" if oldwidth<0.025 and q>b[1] else "SELL" if oldwidth<0.025 and q<b[0] else None
    if strategy_id=="STR-013":
        a=_atr(c); mid=_ema(x,20)
        return "BUY" if a and mid and q>mid+1.5*a else "SELL" if a and mid and q<mid-1.5*a else None
    if strategy_id in ("STR-014","STR-015","STR-052"):
        r=_rsi(x); rp=_rsi(prev)
        if r is None or rp is None:return None
        if strategy_id=="STR-014":return "BUY" if rp<30 and r>=30 else "SELL" if rp>70 and r<=70 else None
        if strategy_id=="STR-015":return _signal_cross(rp,50,r,50)
        a,b=_ema(x,9),_ema(x,21)
        return "BUY" if a>b and r>50 and rp<=50 else "SELL" if a<b and r<50 and rp>=50 else None
    if strategy_id=="STR-017":
        s=_stoch(c)
        return _signal_cross(s[2],s[3],s[0],s[1]) if s and ((s[2]<20 and s[3]<20) or (s[2]>80 and s[3]>80)) else None
    if strategy_id=="STR-019":
        v=_cci(c); old=_cci(c[:-1])
        return "BUY" if old is not None and old<-100 and v is not None and v>=-100 else "SELL" if old is not None and old>100 and v is not None and v<=100 else None
    if strategy_id=="STR-020":
        v=_willr(c); old=_willr(c[:-1])
        return "BUY" if old is not None and old<-80 and v is not None and v>=-80 else "SELL" if old is not None and old>-20 and v is not None and v<=-20 else None
    if strategy_id in ("STR-022","STR-023","STR-024","STR-055"):
        v=_vwap(c); old=_vwap(c[:-1])
        if v is None or old is None:return None
        if strategy_id=="STR-022":
            o=_obv(c);return "BUY" if q>_ema(x,20) and o and o>0 else "SELL" if q<_ema(x,20) and o and o<0 else None
        if strategy_id=="STR-023":return "BUY" if p<=old and q>v else None
        if strategy_id=="STR-024":return "SELL" if p>=old and q<v else None
        r=_rsi(x);return "BUY" if q>v and r and r>50 else "SELL" if q<v and r and r<50 else None
    if strategy_id=="STR-025":
        a=_atr(c);rng=c[-1]["high"]-c[-1]["low"]
        return "BUY" if a and rng>1.5*a and q>c[-1]["open"] else "SELL" if a and rng>1.5*a and q<c[-1]["open"] else None
    if strategy_id in ("STR-033","STR-034"):
        a,b=c[-2],c[-1]
        bull=a["close"]<a["open"] and b["close"]>b["open"] and b["open"]<=a["close"] and b["close"]>=a["open"]
        bear=a["close"]>a["open"] and b["close"]<b["open"] and b["open"]>=a["close"] and b["close"]<=a["open"]
        return "BUY" if strategy_id=="STR-033" and bull else "SELL" if strategy_id=="STR-034" and bear else None
    if strategy_id=="STR-035":
        z=c[-1];body=abs(z["close"]-z["open"]);lower=min(z["open"],z["close"])-z["low"];upper=z["high"]-max(z["open"],z["close"])
        return "BUY" if lower>2*max(body,1e-12) and upper<body else "SELL" if upper>2*max(body,1e-12) and lower<body else None
    if strategy_id=="STR-036":
        a,b=c[-2],c[-1]
        return "BUY" if b["close"]>a["high"] else "SELL" if b["close"]<a["low"] else None
    if strategy_id in ("STR-037","STR-038"):
        z=c[-3:]
        up=all(v["close"]>v["open"] for v in z);down=all(v["close"]<v["open"] for v in z)
        return "BUY" if strategy_id=="STR-037" and up else "SELL" if strategy_id=="STR-038" and down else None
    if strategy_id in ("STR-039","STR-040"):
        a,b,d=c[-3:]
        morning=a["close"]<a["open"] and abs(b["close"]-b["open"])<abs(a["close"]-a["open"])*.5 and d["close"]>d["open"] and d["close"]>(a["open"]+a["close"])/2
        evening=a["close"]>a["open"] and abs(b["close"]-b["open"])<abs(a["close"]-a["open"])*.5 and d["close"]<d["open"] and d["close"]<(a["open"]+a["close"])/2
        return "BUY" if strategy_id=="STR-039" and morning else "SELL" if strategy_id=="STR-040" and evening else None
    if strategy_id=="STR-044":
        ha=[((v["open"]+v["close"])/2,(v["high"]+v["low"]+v["open"]+v["close"])/4) for v in c[-3:]]
        return "BUY" if ha[-1][1]>ha[-1][0] and ha[-2][1]<=ha[-2][0] else "SELL" if ha[-1][1]<ha[-1][0] and ha[-2][1]>=ha[-2][0] else None
    if strategy_id in ("STR-045","STR-046"):
        vols=[float(v.get("volume",0)) for v in c[-21:-1]];vol=float(c[-1].get("volume",0))
        if strategy_id=="STR-045":
            return "BUY" if vols and vol>2*(sum(vols)/len(vols)) and q>p else "SELL" if vols and vol>2*(sum(vols)/len(vols)) and q<p else None
        w=c[-20:];mf=[]
        for v in w:
            rng=v["high"]-v["low"];mult=0 if rng==0 else ((2*v["close"]-v["high"]-v["low"])/rng)*float(v.get("volume",0))
            mf.append(mult)
        total=sum(float(v.get("volume",0)) for v in w)
        cmf=sum(mf)/total if total else 0
        return "BUY" if cmf>0.1 else "SELL" if cmf<-.1 else None
    if strategy_id in ("STR-058","STR-059","STR-060","STR-061","STR-062"):
        if len(c)<16:return None
        w=c[-11:-1];bar=c[-1];hi=max(float(v["high"]) for v in w);lo=min(float(v["low"]) for v in w)
        # Liquidity sweep: trade through a prior 10-bar extreme and close back inside.
        if strategy_id=="STR-058":
            return "BUY" if float(bar["low"])<lo and q>lo else "SELL" if float(bar["high"])>hi and q<hi else None
        # BOS / CHoCH proxy: confirmed close beyond the prior swing range.
        if strategy_id in ("STR-059","STR-060"):
            old=c[-2];old_hi=max(float(v["high"]) for v in c[-12:-2]);old_lo=min(float(v["low"]) for v in c[-12:-2])
            if strategy_id=="STR-059":
                return "BUY" if q>hi else "SELL" if q<lo else None
            return "BUY" if q>old_hi and float(old["close"])<old_hi else "SELL" if q<old_lo and float(old["close"])>old_lo else None
        # FVG retest: current candle overlaps a still-open three-candle imbalance and closes in its direction.
        if strategy_id=="STR-061":
            a,b=c[-3],c[-2]
            bull=float(b["low"])>float(a["high"]) and float(bar["low"])<=float(b["low"]) and q>float(a["high"])
            bear=float(b["high"])<float(a["low"]) and float(bar["high"])>=float(b["high"]) and q<float(a["low"])
            return "BUY" if bull else "SELL" if bear else None
        # Order-block retest proxy: return to last opposing candle before a 10-bar structure break.
        if strategy_id=="STR-062":
            prior=c[-16:-1];base_hi=max(float(v["high"]) for v in prior[-10:]);base_lo=min(float(v["low"]) for v in prior[-10:])
            bull_break=q>base_hi;bear_break=q<base_lo
            if bull_break:
                ob=next((v for v in reversed(prior[-5:]) if float(v["close"])<float(v["open"])),None)
                return "BUY" if ob and float(bar["low"])<=float(ob["open"]) and q>float(ob["open"]) else None
            if bear_break:
                ob=next((v for v in reversed(prior[-5:]) if float(v["close"])>float(v["open"])),None)
                return "SELL" if ob and float(bar["high"])>=float(ob["open"]) and q<float(ob["open"]) else None
            return None
    if strategy_id=="STR-047":
        n=25;w=c[-n:]
        hi=max(range(n),key=lambda i:w[i]["high"]);lo=max(range(n),key=lambda i:w[i]["low"])
        up=100*(n-1-hi)/(n-1);dn=100*(n-1-lo)/(n-1)
        return "BUY" if up>dn+20 else "SELL" if dn>up+20 else None
    if strategy_id=="STR-049":
        roc=(q/x[-11]-1)*100
        old=(p/x[-12]-1)*100
        return "BUY" if old<=0<roc else "SELL" if old>=0>roc else None
    return None

SUPPORTED_STRATEGIES = {
 "STR-001","STR-002","STR-003","STR-004","STR-005","STR-006",
 "STR-010","STR-011","STR-012","STR-013","STR-014","STR-015","STR-017",
 "STR-019","STR-020","STR-025",
 "STR-033","STR-034","STR-035","STR-036","STR-037","STR-038","STR-039",
 "STR-040","STR-044","STR-047","STR-048","STR-049",
 "STR-050","STR-052","STR-053","STR-056","STR-057","STR-058","STR-059","STR-060","STR-061","STR-062"
}

def atr_value(candles:list[dict],period:int=14)->float|None:
    return _atr(candles,period)
