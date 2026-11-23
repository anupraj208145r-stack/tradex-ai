from __future__ import annotations
import asyncio, json, os, time, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, desc

from .db import (init_db, SessionLocal, PaperAccount, Position, Trade, Candle,
                CustomStrategy)
from . import providers

BASE=Path(__file__).parent
CATALOG=json.loads((BASE/"strategies.json").read_text())
SYMBOLS=("XAUUSD","BTCUSD")
prices:dict[str,float]={}
quotes_meta:dict[str,dict]={}
candles:dict[str,list[dict]]={s:[] for s in SYMBOLS}
current_candle:dict[str,dict]={}
clients:set[WebSocket]=set()
market_lock=asyncio.Lock()
engine_status="starting"

class OrderIn(BaseModel):
    symbol:Literal["XAUUSD","BTCUSD"]
    side:Literal["BUY","SELL"]
    quantity:float=Field(gt=0,le=100)
    stop_loss:float|None=None
    take_profit:float|None=None
class ResetIn(BaseModel):
    balance:float=Field(gt=0,le=100000000)
class AutoIn(BaseModel):
    enabled:bool
    strategy_id:str|None=None
    risk_pct:float=Field(default=1.0,gt=0,le=5)
class CustomStrategyIn(BaseModel):
    name:str=Field(min_length=3,max_length=60)
    symbol:Literal["XAUUSD","BTCUSD","BOTH"]="BOTH"
    fast_ema:int=Field(default=9,ge=2,le=100)
    slow_ema:int=Field(default=21,ge=3,le=200)
    direction:Literal["both","long_only","short_only"]="both"

def feed_is_fresh(symbol:str,max_age_seconds:int=60)->bool:
    meta=quotes_meta.get(symbol)
    return bool(meta and meta.get("live") is True and providers.STATUS.get(symbol)=="connected" and
                time.time()-int(meta.get("time",0))<=max_age_seconds)

def db_account(db):
    account=db.get(PaperAccount,1)
    if account is None:
        account=PaperAccount(id=1,starting_balance=10000,balance=10000,realized_pnl=0,
                             auto_enabled=False,active_strategy="STR-001",risk_pct=1)
        db.add(account);db.commit();db.refresh(account)
    return account

def position_dict(p):
    return {"id":p.id,"symbol":p.symbol,"side":p.side,"quantity":p.quantity,
        "entry":p.entry,"stop_loss":p.stop_loss,"take_profit":p.take_profit,
        "opened_at":p.opened_at,"source":p.source}

def trade_dict(t):
    return {"id":t.position_id,"symbol":t.symbol,"side":t.side,"quantity":t.quantity,
        "entry":t.entry,"exit":t.exit,"pnl":t.pnl,"reason":t.reason,
        "opened_at":t.opened_at,"closed_at":t.closed_at}

def account_snapshot():
    with SessionLocal() as db:
        a=db_account(db)
        positions=[position_dict(p) for p in db.scalars(select(Position)).all()]
        history=[trade_dict(t) for t in db.scalars(select(Trade).order_by(desc(Trade.closed_at)).limit(100)).all()]
        floating=sum((prices.get(p["symbol"],p["entry"])-p["entry"])*p["quantity"]*(1 if p["side"]=="BUY" else -1) for p in positions)
        return {"balance":round(a.balance,2),"equity":round(a.balance+floating,2),
            "realized_pnl":round(a.realized_pnl,2),"unrealized_pnl":round(floating,2),
            "positions":positions,"history":history,"auto":a.auto_enabled,
            "active_strategy":a.active_strategy,"risk_pct":a.risk_pct}

def get_strategy_items():
    with SessionLocal() as db:
        custom=db.scalars(select(CustomStrategy)).all()
        items=[{"id":s.id,"name":s.name,"category":"Custom",
            "rule_summary":f"EMA {s.fast_ema}/{s.slow_ema}; {s.direction}; {s.symbol}",
            "executable":False,"status":"custom_draft"} for s in custom]
    return CATALOG+items

def ema(values:list[float],period:int):
    if len(values)<period:return None
    k=2/(period+1);result=sum(values[:period])/period
    for v in values[period:]:result=v*k+result*(1-k)
    return result

def persist_candle(symbol:str,c:dict,source:str):
    with SessionLocal() as db:
        row=db.get(Candle,(symbol,"1m",int(c["time"])))
        if row is None:
            row=Candle(symbol=symbol,timeframe="1m",time=int(c["time"]),open=c["open"],
                high=c["high"],low=c["low"],close=c["close"],volume=c.get("volume",0),
                source=source)
            db.add(row)
        else:
            row.high=max(row.high,c["high"]);row.low=min(row.low,c["low"])
            row.close=c["close"];row.volume=c.get("volume",row.volume);row.source=source
        db.commit()

def close_position(position_id:str,reason:str):
    with SessionLocal() as db:
        p=db.get(Position,position_id)
        if p is None:return
        exit_price=prices.get(p.symbol,p.entry)
        pnl=(exit_price-p.entry)*p.quantity*(1 if p.side=="BUY" else -1)
        a=db_account(db);a.balance+=pnl;a.realized_pnl+=pnl;a.updated_at=int(time.time())
        db.add(Trade(position_id=p.id,symbol=p.symbol,side=p.side,quantity=p.quantity,
            entry=p.entry,exit=exit_price,pnl=round(pnl,2),reason=reason,
            opened_at=p.opened_at,closed_at=int(time.time())))
        db.delete(p);db.commit()

def check_exits(symbol:str):
    price=prices.get(symbol)
    if price is None:return
    with SessionLocal() as db:
        positions=db.scalars(select(Position).where(Position.symbol==symbol)).all()
        ids=[]
        for p in positions:
            hit_sl=p.stop_loss is not None and ((p.side=="BUY" and price<=p.stop_loss) or (p.side=="SELL" and price>=p.stop_loss))
            hit_tp=p.take_profit is not None and ((p.side=="BUY" and price>=p.take_profit) or (p.side=="SELL" and price<=p.take_profit))
            if hit_sl:ids.append((p.id,"stop_loss"))
            elif hit_tp:ids.append((p.id,"take_profit"))
    for pid,reason in ids:close_position(pid,reason)

def evaluate_auto(symbol:str):
    with SessionLocal() as db:
        a=db_account(db)
        if not a.auto_enabled or a.active_strategy!="STR-001":return
        if any(not feed_is_fresh(s) for s in SYMBOLS):return
        if db.scalar(select(Position.id).where(Position.symbol==symbol)) is not None:return
        series=candles[symbol]
        closes=[float(c["close"]) for c in series]
        if len(closes)<22:return
        fast_now=ema(closes,9);slow_now=ema(closes,21)
        fast_prev=ema(closes[:-1],9);slow_prev=ema(closes[:-1],21)
        if None in (fast_now,slow_now,fast_prev,slow_prev):return
        side=None
        if fast_prev<=slow_prev and fast_now>slow_now:side="BUY"
        elif fast_prev>=slow_prev and fast_now<slow_now:side="SELL"
        if side is None:return
        entry=prices.get(symbol)
        if entry is None:return
        stop_distance=entry*0.01
        risk_cash=a.balance*a.risk_pct/100
        qty=min(100.0,max(0.001,round(risk_cash/stop_distance,3)))
        sl=entry-stop_distance if side=="BUY" else entry+stop_distance
        tp=entry+2*stop_distance if side=="BUY" else entry-2*stop_distance
        db.add(Position(id=uuid.uuid4().hex,symbol=symbol,side=side,quantity=qty,
            entry=entry,stop_loss=sl,take_profit=tp,opened_at=int(time.time()),source="auto"))
        db.commit()

async def publish():
    if not clients:return
    message={"quotes":quotes_meta,"account":account_snapshot(),"feeds":providers.STATUS}
    dead=[]
    for ws in list(clients):
        try:await ws.send_json(message)
        except Exception:dead.append(ws)
    for ws in dead:clients.discard(ws)

async def on_tick(symbol:str,price:float,timestamp:int,source:str):
    if price<=0:return
    async with market_lock:
        prices[symbol]=price
        quotes_meta[symbol]={"symbol":symbol,"price":round(price,5),"time":timestamp,
            "feed":source,"status":"connected","live":True}
        minute=timestamp-(timestamp%60)
        current=current_candle.get(symbol)
        closed=False
        if current is None:
            current={"time":minute,"open":price,"high":price,"low":price,"close":price,"volume":0}
            current_candle[symbol]=current
        elif current["time"]==minute:
            current["high"]=max(current["high"],price);current["low"]=min(current["low"],price);current["close"]=price
        else:
            finished=current.copy()
            candles[symbol].append(finished);candles[symbol]=candles[symbol][-1000:]
            persist_candle(symbol,finished,source);closed=True
            current={"time":minute,"open":price,"high":price,"low":price,"close":price,"volume":0}
            current_candle[symbol]=current
        if closed:evaluate_auto(symbol)
        check_exits(symbol)
    await publish()

async def market_worker(symbol:str):
    try:
        history=await providers.history(symbol)
        if history:
            merged={int(c["time"]):{k:c[k] for k in ("time","open","high","low","close")} for c in candles[symbol]}
            for c in history:
                merged[int(c["time"]) ]={k:c[k] for k in ("time","open","high","low","close")}
                persist_candle(symbol,c,c.get("source","history"))
            candles[symbol]=[merged[t] for t in sorted(merged)][-1000:]
            last=history[-1]
            prices[symbol]=float(last["close"])
            quotes_meta[symbol]={"symbol":symbol,"price":prices[symbol],"time":last["time"],
                "feed":last.get("source","history"),"status":"history_only","live":False}
            current_candle[symbol]={k:last[k] for k in ("time","open","high","low","close")}
    except Exception as exc:
        providers.LAST_ERROR[symbol]=str(exc)[:240]
    if symbol=="BTCUSD":
        await providers.coinbase_stream(on_tick)
    else:
        await providers.gold_stream(on_tick)

@asynccontextmanager
async def lifespan(app:FastAPI):
    global engine_status
    init_db()
    with SessionLocal() as db:
        a=db_account(db)
        # Resume only when explicitly enabled by deployment configuration.
        if os.getenv("AUTO_RESUME_ON_RESTART","false").lower() not in ("1","true","yes"):
            a.auto_enabled=False
        db.commit()
        for p in db.scalars(select(Position)).all():
            pass
        for symbol in SYMBOLS:
            rows=db.scalars(select(Candle).where(Candle.symbol==symbol,Candle.timeframe=="1m").order_by(desc(Candle.time)).limit(1000)).all()
            candles[symbol]=[{"time":r.time,"open":r.open,"high":r.high,"low":r.low,"close":r.close} for r in reversed(rows)]
            if candles[symbol]:
                last=candles[symbol][-1];prices[symbol]=last["close"]
                quotes_meta[symbol]={"symbol":symbol,"price":last["close"],"time":last["time"],"feed":"database","status":"history_only","live":False}
    engine_status="running"
    tasks=[asyncio.create_task(market_worker(s)) for s in SYMBOLS]
    try:yield
    finally:
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        engine_status="stopped"

app=FastAPI(title="TradeX AI Paper Trading API",version="0.2.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=os.getenv("CORS_ORIGINS","http://localhost:8000").split(","),allow_methods=["GET","POST"],allow_headers=["Content-Type"])

@app.get("/api/health")
def health():
    ready={s:feed_is_fresh(s) for s in SYMBOLS}
    return {"ok":True,"engine":engine_status,"mode":"PAPER_ONLY","broker_connected":False,
        "feeds":providers.STATUS,"last_errors":providers.LAST_ERROR,"live_ready":ready}

@app.get("/api/account")
def account():return account_snapshot()

@app.post("/api/account/reset")
def reset(req:ResetIn):
    with SessionLocal() as db:
        a=db_account(db);a.starting_balance=req.balance;a.balance=req.balance;a.realized_pnl=0
        a.auto_enabled=False;a.updated_at=int(time.time())
        for p in db.scalars(select(Position)).all():db.delete(p)
        db.query(Trade).delete();db.commit()
    return account_snapshot()

@app.get("/api/quotes")
def quotes():return quotes_meta

@app.get("/api/candles/{symbol}")
def get_candles(symbol:str):
    if symbol not in SYMBOLS:raise HTTPException(404,"Unknown symbol")
    return candles[symbol]+([current_candle[symbol]] if symbol in current_candle else [])

@app.get("/api/strategies")
def strategies():return get_strategy_items()

@app.post("/api/orders")
def order(req:OrderIn):
    if req.symbol not in prices or not feed_is_fresh(req.symbol):raise HTTPException(503,"No fresh live market price available yet for this symbol")
    with SessionLocal() as db:
        a=db_account(db)
        if req.quantity*prices[req.symbol]>max(a.balance,0)*5:
            raise HTTPException(400,"Paper order notional exceeds 5x account balance")
        p=Position(id=uuid.uuid4().hex,symbol=req.symbol,side=req.side,quantity=req.quantity,
            entry=prices[req.symbol],stop_loss=req.stop_loss,take_profit=req.take_profit,
            opened_at=int(time.time()),source="manual")
        db.add(p);db.commit()
    return {"accepted":True,"mode":"PAPER_ONLY","position":position_dict(p),"account":account_snapshot()}

@app.post("/api/positions/{position_id}/close")
def close(position_id:str):
    with SessionLocal() as db:
        p=db.get(Position,position_id)
        if p is None:raise HTTPException(404,"Position not found")
    close_position(position_id,"manual")
    return account_snapshot()

@app.post("/api/auto")
def auto(req:AutoIn):
    if req.enabled:
        item=next((s for s in get_strategy_items() if s["id"]==(req.strategy_id or "STR-001")),None)
        if item is None:raise HTTPException(404,"Strategy not found")
        if not item.get("executable"):raise HTTPException(400,"Strategy is not executable")
        if item["id"]!="STR-001":raise HTTPException(400,"Only EMA 9/21 is implemented in this milestone")
        if any(not feed_is_fresh(s) for s in SYMBOLS):
            raise HTTPException(503,"Both live feeds must be connected before enabling auto trading")
    with SessionLocal() as db:
        a=db_account(db);a.auto_enabled=req.enabled;a.risk_pct=req.risk_pct
        if req.enabled:a.active_strategy=req.strategy_id or "STR-001"
        db.commit()
    return account_snapshot()

@app.post("/api/strategies/custom")
def custom(req:CustomStrategyIn):
    if req.fast_ema>=req.slow_ema:raise HTTPException(400,"Fast EMA must be smaller than slow EMA")
    item=CustomStrategy(id="CUSTOM-"+uuid.uuid4().hex[:10],name=req.name,symbol=req.symbol,
        fast_ema=req.fast_ema,slow_ema=req.slow_ema,direction=req.direction,created_at=int(time.time()))
    with SessionLocal() as db:db.add(item);db.commit()
    return {"id":item.id,"name":item.name,"category":"Custom",
        "rule_summary":f"EMA {item.fast_ema}/{item.slow_ema}; {item.direction}; {item.symbol}",
        "executable":False,"status":"custom_draft"}

@app.websocket("/ws/market")
async def ws_market(ws:WebSocket):
    await ws.accept();clients.add(ws)
    try:
        await ws.send_json({"quotes":quotes_meta,"account":account_snapshot(),"feeds":providers.STATUS})
        while True:await ws.receive_text()
    except WebSocketDisconnect:clients.discard(ws)
    except Exception:clients.discard(ws)

app.mount("/",StaticFiles(directory=BASE.parent/"frontend",html=True),name="frontend")
