from __future__ import annotations
import asyncio, json, os, time, uuid, re, math, logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func

from .db import (init_db, SessionLocal, engine, Candle, PaperAccount, Position, Trade, UserPaperAccount, UserPosition, UserTrade, UserCustomStrategy, UserRiskState, SupportTicket)
from .auth import current_user, verify_access_token
import httpx
from . import providers
from .strategy_engine import signal_for, SUPPORTED_STRATEGIES, atr_value
from .risk_engine import POLICY, evaluate_rules

BASE=Path(__file__).parent
CATALOG=json.loads((BASE/"strategies.json").read_text())
SYMBOLS=("XAUUSD","BTCUSD")
CONTRACT_SIZE={"XAUUSD":100.0,"BTCUSD":1.0}
MAX_POSITION_NOTIONAL_MULTIPLE=5.0
MAX_RISK_PER_TRADE_PCT=0.5
prices:dict[str,float]={}
quotes_meta:dict[str,dict]={}
candles:dict[str,list[dict]]={s:[] for s in SYMBOLS}
current_candle:dict[str,dict]={}
clients:dict[WebSocket,str]={}
market_lock=asyncio.Lock()
engine_status="starting"
last_auto_bar:dict[tuple[str,str,str],int]={}
last_live_prices:dict[str,float]={}
pending_live_prices:dict[str,float]={}
MAX_TICK_MOVE_PCT={"XAUUSD":0.008,"BTCUSD":0.03}
MAX_CANDLE_RANGE_PCT={"XAUUSD":0.01,"BTCUSD":0.05}
logger=logging.getLogger("tradex.api")


class SupportRequestIn(BaseModel):
    name:str=Field(min_length=2,max_length=80)
    email:str=Field(min_length=5,max_length=254)
    category:Literal["Account access","Market data","Paper trading","Strategy library","Bug report","Feedback","Other"]
    subject:str=Field(min_length=4,max_length=120)
    message:str=Field(min_length=15,max_length=5000)
    website:str=Field(default="",max_length=200)

class SupportUpdateIn(BaseModel):
    status:Literal["new","in_progress","resolved"]
    admin_note:str=Field(default="",max_length=2000)

def admin_emails()->set[str]:
    return {item.strip().lower() for item in os.getenv("ADMIN_EMAILS","").split(",") if item.strip()}

def require_admin(user=Depends(current_user)):
    allowed=admin_emails()
    if not allowed:
        raise HTTPException(status_code=503,detail="Admin access is not configured")
    if not user.get("email") or user["email"].lower() not in allowed:
        raise HTTPException(status_code=403,detail="Admin access required")
    return user

def send_support_email(to_email:str,subject:str,body:str)->bool:
    api_key=os.getenv("RESEND_API_KEY","").strip()
    sender=os.getenv("RESEND_FROM_EMAIL","").strip()
    if not api_key or not sender:
        return False
    try:
        response=httpx.post("https://api.resend.com/emails",
            headers={"Authorization":"Bearer "+api_key,"Content-Type":"application/json"},
            json={"from":sender,"to":[to_email],"subject":subject,"text":body},
            timeout=10.0)
        return response.status_code in (200,201,202)
    except httpx.HTTPError:
        return False

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
    risk_pct:float=Field(default=0.5,gt=0,le=0.5)
    timeframe:Literal["1m","5m","15m","30m","1h","4h","1d"]="1m"
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

def legacy_account_is_untouched(balance:float,starting_balance:float,realized_pnl:float,
                                 has_positions:bool,has_trades:bool)->bool:
    known_defaults=(1000.0,10000.0)
    return (any(abs(float(starting_balance)-value)<0.005 for value in known_defaults)
            and abs(float(balance)-float(starting_balance))<0.005
            and abs(float(realized_pnl))<0.005
            and not has_positions and not has_trades)


def db_account(db,user_id:str):
    account=db.get(UserPaperAccount,user_id)
    legacy=db.get(PaperAccount,1)
    if account is None:
        any_user_account=db.scalar(select(UserPaperAccount.user_id).limit(1))
        if any_user_account is None and legacy is not None:
            account=UserPaperAccount(user_id=user_id,starting_balance=legacy.starting_balance,
                balance=legacy.balance,realized_pnl=legacy.realized_pnl,auto_enabled=False,
                active_strategy=legacy.active_strategy,active_timeframe=legacy.active_timeframe,
                risk_pct=legacy.risk_pct,legacy_migrated=True,updated_at=legacy.updated_at)
            db.add(account)
            for old in db.scalars(select(Position)).all():
                if db.get(UserPosition,old.id) is None:
                    db.add(UserPosition(id=old.id,user_id=user_id,symbol=old.symbol,side=old.side,
                        quantity=old.quantity,entry=old.entry,stop_loss=old.stop_loss,
                        take_profit=old.take_profit,opened_at=old.opened_at,source=old.source))
            for old in db.scalars(select(Trade).order_by(Trade.closed_at)).all():
                exists=db.scalar(select(UserTrade.id).where(
                    UserTrade.user_id==user_id,UserTrade.position_id==old.position_id,
                    UserTrade.closed_at==old.closed_at).limit(1))
                if not exists:
                    db.add(UserTrade(user_id=user_id,position_id=old.position_id,symbol=old.symbol,
                        side=old.side,quantity=old.quantity,entry=old.entry,exit=old.exit,pnl=old.pnl,
                        reason=old.reason,opened_at=old.opened_at,closed_at=old.closed_at))
        else:
            account=UserPaperAccount(user_id=user_id,starting_balance=1000,balance=1000,realized_pnl=0,
                                     auto_enabled=False,active_strategy="STR-001",risk_pct=1,legacy_migrated=True)
            db.add(account)
        db.commit();db.refresh(account)
    else:
        # Recover the legacy single-user account only when this is the sole
        # per-user account and the current account is still untouched default.
        # Never overwrite an account that already contains user activity.
        user_count=db.query(func.count(UserPaperAccount.user_id)).scalar() or 0
        current_positions=db.scalar(select(UserPosition.id).where(UserPosition.user_id==user_id).limit(1))
        current_trades=db.scalar(select(UserTrade.id).where(UserTrade.user_id==user_id).limit(1))
        legacy_positions=db.scalar(select(Position.id).limit(1))
        legacy_trades=db.scalar(select(Trade.id).limit(1))
        untouched=legacy_account_is_untouched(account.balance,account.starting_balance,
            account.realized_pnl,current_positions is not None,current_trades is not None)
        legacy_has_data=bool(legacy and (
            abs(float(legacy.balance)-float(legacy.starting_balance))>=0.005 or
            abs(float(legacy.realized_pnl))>=0.005 or legacy_positions or legacy_trades))
        # Attempt a one-time legacy import only for the sole untouched default account.
        if not account.legacy_migrated and user_count==1 and untouched and legacy_has_data:
            account.starting_balance=legacy.starting_balance
            account.balance=legacy.balance
            account.realized_pnl=legacy.realized_pnl
            account.active_strategy=legacy.active_strategy
            account.active_timeframe=legacy.active_timeframe
            account.risk_pct=legacy.risk_pct
            account.auto_enabled=False
            account.updated_at=legacy.updated_at
            for old in db.scalars(select(Position)).all():
                if db.get(UserPosition,old.id) is None:
                    db.add(UserPosition(id=old.id,user_id=user_id,symbol=old.symbol,side=old.side,
                        quantity=old.quantity,entry=old.entry,stop_loss=old.stop_loss,
                        take_profit=old.take_profit,opened_at=old.opened_at,source=old.source))
            for old in db.scalars(select(Trade).order_by(Trade.closed_at)).all():
                exists=db.scalar(select(UserTrade.id).where(
                    UserTrade.user_id==user_id,UserTrade.position_id==old.position_id,
                    UserTrade.closed_at==old.closed_at).limit(1))
                if not exists:
                    db.add(UserTrade(user_id=user_id,position_id=old.position_id,symbol=old.symbol,
                        side=old.side,quantity=old.quantity,entry=old.entry,exit=old.exit,pnl=old.pnl,
                        reason=old.reason,opened_at=old.opened_at,closed_at=old.closed_at))
            db.commit();db.refresh(account)
    if not account.legacy_migrated:
        account.legacy_migrated=True
        db.commit();db.refresh(account)
    return account

def position_dict(p):
    return {"id":p.id,"symbol":p.symbol,"side":p.side,"quantity":p.quantity,
        "entry":p.entry,"stop_loss":p.stop_loss,"take_profit":p.take_profit,
        "opened_at":p.opened_at,"source":p.source}

def trade_dict(t):
    return {"id":t.position_id,"symbol":t.symbol,"side":t.side,"quantity":t.quantity,
        "entry":t.entry,"exit":t.exit,"pnl":t.pnl,"reason":t.reason,
        "opened_at":t.opened_at,"closed_at":t.closed_at}

def account_snapshot(user_id:str):
    with SessionLocal() as db:
        a=db_account(db,user_id)
        raw_positions=db.scalars(select(UserPosition).where(UserPosition.user_id==user_id)).all()
        floating=0.0
        positions=[]
        for p in raw_positions:
            mark=float(prices.get(p.symbol,p.entry))
            pnl=(mark-p.entry)*p.quantity*CONTRACT_SIZE.get(p.symbol,1.0)*(1 if p.side=="BUY" else -1)
            floating+=pnl
            item=position_dict(p)
            item.update({"mark_price":round(mark,5),"unrealized_pnl":round(pnl,2)})
            positions.append(item)
        equity=float(a.balance)+floating
        today=time.strftime("%Y-%m-%d",time.gmtime())
        state=db.get(UserRiskState,user_id)
        if state is None:
            state=UserRiskState(user_id=user_id,day_key=today,day_start_equity=equity,
                peak_equity=equity,daily_locked=False,overall_failed=False,
                challenge_passed=False,lock_reason="",updated_at=int(time.time()))
            db.add(state)
        result=evaluate_rules(starting_balance=a.starting_balance,
            day_start_equity=state.day_start_equity,equity=equity,
            state={"day_key":state.day_key,"daily_locked":state.daily_locked,
                "overall_failed":state.overall_failed,"challenge_passed":state.challenge_passed,
                "lock_reason":state.lock_reason},today=today)
        state.day_key=result["day_key"];state.day_start_equity=result["day_start_equity"]
        state.peak_equity=max(float(state.peak_equity or equity),equity)
        state.daily_locked=result["daily_locked"];state.overall_failed=result["overall_failed"]
        state.challenge_passed=result["challenge_passed"];state.lock_reason=result["lock_reason"]
        state.updated_at=int(time.time())
        if result["status"]!="ACTIVE":
            a.auto_enabled=False
        db.commit()
        history=[trade_dict(t) for t in db.scalars(select(UserTrade).where(UserTrade.user_id==user_id).order_by(desc(UserTrade.closed_at)).limit(100)).all()]
        return {"balance":round(a.balance,2),"equity":round(equity,2),
            "realized_pnl":round(a.realized_pnl,2),"unrealized_pnl":round(floating,2),
            "positions":positions,"history":history,"auto":a.auto_enabled,
            "active_strategy":a.active_strategy,"active_timeframe":a.active_timeframe,
            "risk_pct":a.risk_pct,"risk":result}

def get_strategy_items(user_id:str):
    with SessionLocal() as db:
        custom=db.scalars(select(UserCustomStrategy).where(UserCustomStrategy.user_id==user_id)).all()
        items=[{"id":s.id,"name":s.name,"category":"Custom",
            "rule_summary":f"EMA {s.fast_ema}/{s.slow_ema}; {s.direction}; {s.symbol}",
            "executable":True,"status":"implemented"} for s in custom]
    return CATALOG+items

def ema(values:list[float],period:int):
    if len(values)<period:return None
    k=2/(period+1);result=sum(values[:period])/period
    for v in values[period:]:result=v*k+result*(1-k)
    return result

def market_candle_is_valid(symbol:str,c:dict)->bool:
    try:
        o,h,l,cl=(float(c[k]) for k in ("open","high","low","close"))
    except (KeyError,TypeError,ValueError):
        return False
    if not all(math.isfinite(v) and v>0 for v in (o,h,l,cl)):
        return False
    if h < max(o,cl) or l > min(o,cl) or h < l:
        return False
    return (h-l)/((o+cl)/2) <= MAX_CANDLE_RANGE_PCT.get(symbol,0.05)


def sanitize_market_candles(symbol:str,rows:list[dict])->list[dict]:
    by_time={}
    for c in rows:
        try: stamp=int(c["time"])
        except (KeyError,TypeError,ValueError): continue
        if market_candle_is_valid(symbol,c):
            item={k:(stamp if k=="time" else float(c[k])) for k in ("time","open","high","low","close")}
            if "volume" in c:
                try:item["volume"]=max(0.0,float(c["volume"]))
                except (TypeError,ValueError):item["volume"]=0.0
            by_time[stamp]=item
    return [by_time[t] for t in sorted(by_time)][-1000:]


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

def close_position(user_id:str,position_id:str,reason:str):
    with SessionLocal() as db:
        p=db.scalar(select(UserPosition).where(UserPosition.id==position_id,UserPosition.user_id==user_id))
        if p is None:return
        exit_price=prices.get(p.symbol,p.entry)
        pnl=(exit_price-p.entry)*p.quantity*CONTRACT_SIZE.get(p.symbol,1.0)*(1 if p.side=="BUY" else -1)
        a=db_account(db,user_id);a.balance+=pnl;a.realized_pnl+=pnl;a.updated_at=int(time.time())
        db.add(UserTrade(user_id=user_id,position_id=p.id,symbol=p.symbol,side=p.side,quantity=p.quantity,
            entry=p.entry,exit=exit_price,pnl=round(pnl,2),reason=reason,
            opened_at=p.opened_at,closed_at=int(time.time())))
        db.delete(p);db.commit()

def check_exits(symbol:str):
    price=prices.get(symbol)
    if price is None:return
    with SessionLocal() as db:
        positions=db.scalars(select(UserPosition).where(UserPosition.symbol==symbol)).all()
        ids=[]
        for p in positions:
            hit_sl=p.stop_loss is not None and ((p.side=="BUY" and price<=p.stop_loss) or (p.side=="SELL" and price>=p.stop_loss))
            hit_tp=p.take_profit is not None and ((p.side=="BUY" and price>=p.take_profit) or (p.side=="SELL" and price<=p.take_profit))
            if hit_sl:ids.append((p.user_id,p.id,"stop_loss"))
            elif hit_tp:ids.append((p.user_id,p.id,"take_profit"))
    for uid,pid,reason in ids:close_position(uid,pid,reason)

def adaptive_levels(symbol:str,side:str,entry:float,series:list[dict]):
    atr=atr_value(series,14)
    if atr is None or atr<=0:return None
    distance=max(atr*1.5,entry*0.0005)
    return (entry-distance,entry+distance*2) if side=="BUY" else (entry+distance,entry-distance*2)

def evaluate_auto(symbol:str):
    if not feed_is_fresh(symbol):return
    with SessionLocal() as db:
        accounts=db.scalars(select(UserPaperAccount).where(UserPaperAccount.auto_enabled.is_(True))).all()
        for account in accounts:
            # Re-evaluate limits on every market tick before the bot can create a new order.
            if account_snapshot(account.user_id)["risk"]["status"] != "ACTIVE":
                account.auto_enabled=False
                continue
            series=aggregate_candles(candles[symbol],account.active_timeframe or "1m")
            if len(series)<55:continue
            bar_time=int(series[-1]["time"]);bar_key=(account.user_id,symbol,account.active_timeframe or "1m")
            if last_auto_bar.get(bar_key)==bar_time:continue
            last_auto_bar[bar_key]=bar_time
            if db.scalar(select(UserPosition.id).where(UserPosition.user_id==account.user_id,UserPosition.symbol==symbol)) is not None:continue
            strategy_id=account.active_strategy
            if strategy_id.startswith("CUSTOM-"):
                custom=db.get(UserCustomStrategy,strategy_id)
                if custom is None or custom.user_id!=account.user_id:continue
                closes=[float(c["close"]) for c in series]
                fast,slow=ema(closes,custom.fast_ema),ema(closes,custom.slow_ema)
                fp,sp=ema(closes[:-1],custom.fast_ema),ema(closes[:-1],custom.slow_ema)
                side="BUY" if fp is not None and sp is not None and fp<=sp and fast>slow else "SELL" if fp is not None and sp is not None and fp>=sp and fast<slow else None
                if side=="BUY" and custom.direction=="short_only":side=None
                if side=="SELL" and custom.direction=="long_only":side=None
                if custom.symbol not in (symbol,"BOTH"):side=None
            else:
                if strategy_id not in SUPPORTED_STRATEGIES:continue
                side=signal_for(strategy_id,series)
            if side is None:continue
            entry=prices.get(symbol)
            if entry is None:continue
            levels=adaptive_levels(symbol,side,entry,series)
            if levels is None:continue
            sl,tp=levels
            risk_cash=max(account.balance,0)*min(account.risk_pct,MAX_RISK_PER_TRADE_PCT)/100
            qty=min(100.0,round(risk_cash/(abs(entry-sl)*CONTRACT_SIZE[symbol]),6))
            qty=min(qty,max(account.balance,0)*MAX_POSITION_NOTIONAL_MULTIPLE/(entry*CONTRACT_SIZE[symbol]))
            if qty<0.001:continue
            db.add(UserPosition(id=uuid.uuid4().hex,user_id=account.user_id,symbol=symbol,side=side,quantity=qty,
                entry=entry,stop_loss=sl,take_profit=tp,opened_at=int(time.time()),source="auto"))
        db.commit()

def trail_auto_positions(symbol:str):
    atr=atr_value(candles[symbol],14);price=prices.get(symbol)
    if atr is None or atr<=0 or price is None:return
    distance=atr*1.5
    with SessionLocal() as db:
        positions=db.scalars(select(UserPosition).where(UserPosition.symbol==symbol,UserPosition.source=="auto")).all()
        for p in positions:
            candidate=price-distance if p.side=="BUY" else price+distance
            if p.side=="BUY" and candidate>p.entry and (p.stop_loss is None or candidate>p.stop_loss):p.stop_loss=candidate
            if p.side=="SELL" and candidate<p.entry and (p.stop_loss is None or candidate<p.stop_loss):p.stop_loss=candidate
        db.commit()

async def publish():
    if not clients:return
    dead=[]
    for ws,user_id in list(clients.items()):
        try:
            await ws.send_json({"quotes":quotes_meta,"feeds":providers.STATUS})
            try:
                await ws.send_json({"account":account_snapshot(user_id)})
            except Exception as exc:
                await ws.send_json({"account_error":"Account data temporarily unavailable"})
        except Exception:
            dead.append(ws)
    for ws in dead:clients.pop(ws,None)

async def on_tick(symbol:str,price:float,timestamp:int,source:str):
    if symbol not in SYMBOLS or not math.isfinite(float(price)) or price<=0:return
    now=int(time.time())
    if timestamp>10_000_000_000:timestamp=int(timestamp/1000)
    if timestamp<=0 or abs(int(timestamp)-now)>120:return
    async with market_lock:
        minute=timestamp-(timestamp%60)
        current=current_candle.get(symbol)
        if current is not None and minute < int(current["time"]):
            return
        reference=last_live_prices.get(symbol,prices.get(symbol))
        threshold=MAX_TICK_MOVE_PCT.get(symbol,0.03)
        if reference and abs(float(price)-float(reference))/float(reference)>threshold:
            pending=pending_live_prices.get(symbol)
            if pending and abs(float(price)-pending)/pending<=threshold*0.2:
                pending_live_prices.pop(symbol,None)
                last_live_prices[symbol]=float(price)
            else:
                pending_live_prices[symbol]=float(price)
                return
        else:
            pending_live_prices.pop(symbol,None)
            last_live_prices[symbol]=float(price)
        prices[symbol]=float(price)
        quotes_meta[symbol]={"symbol":symbol,"price":round(float(price),5),"time":timestamp,
            "feed":source,"status":"connected","live":True}
        closed=False
        if current is None:
            current={"time":minute,"open":price,"high":price,"low":price,"close":price,"volume":0}
            current_candle[symbol]=current
        elif current["time"]==minute:
            current["high"]=max(current["high"],price);current["low"]=min(current["low"],price);current["close"]=price
        else:
            finished=current.copy()
            if market_candle_is_valid(symbol,finished):
                candles[symbol].append(finished);candles[symbol]=candles[symbol][-1000:]
                persist_candle(symbol,finished,source);closed=True
            current={"time":minute,"open":price,"high":price,"low":price,"close":price,"volume":0}
            current_candle[symbol]=current
        if closed:evaluate_auto(symbol)
        trail_auto_positions(symbol)
        check_exits(symbol)
    await publish()

async def market_worker(symbol:str):
    try:
        history=await providers.history(symbol)
        history=sanitize_market_candles(symbol,history)
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
        # Pause every user's automated strategy on restart.
        db.query(UserPaperAccount).update({UserPaperAccount.auto_enabled:False})
        db.commit()
        for symbol in SYMBOLS:
            rows=db.scalars(select(Candle).where(Candle.symbol==symbol,Candle.timeframe=="1m").order_by(desc(Candle.time)).limit(1000)).all()
            candles[symbol]=sanitize_market_candles(symbol,[{"time":r.time,"open":r.open,"high":r.high,"low":r.low,"close":r.close} for r in reversed(rows)])
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

@app.exception_handler(Exception)
async def unhandled_api_error(request:Request,exc:Exception):
    logger.exception("Unhandled request error: %s %s",request.method,request.url.path)
    return JSONResponse(status_code=500,content={"detail":"Internal server error","path":request.url.path})

@app.get("/api/health")
def health():
    now=int(time.time())
    ready={s:feed_is_fresh(s) for s in SYMBOLS}
    ages={s:(max(0,now-int(quotes_meta[s].get("time",0))) if s in quotes_meta and quotes_meta[s].get("live") else None) for s in SYMBOLS}
    return {"ok":True,"engine":engine_status,"mode":"PAPER_ONLY","broker_connected":False,
        "feeds":providers.STATUS,"last_errors":providers.LAST_ERROR,
        "live_ready":ready,"feed_age_seconds":ages}

@app.get("/api/me")
def me(user=Depends(current_user)):return {"id":user["id"],"email":user.get("email"),"phone":user.get("phone")}

@app.get("/api/account/diagnostics")
def account_diagnostics(user=Depends(current_user)):
    with SessionLocal() as db:
        uid=user["id"]
        account=db.get(UserPaperAccount,uid)
        legacy=db.get(PaperAccount,1)
        return {
            "authenticated":True,
            "user_account_exists":account is not None,
            "user_balance":round(float(account.balance),2) if account else None,
            "user_realized_pnl":round(float(account.realized_pnl),2) if account else None,
            "user_positions":db.scalar(select(func.count()).select_from(UserPosition).where(UserPosition.user_id==uid)) or 0,
            "user_trades":db.scalar(select(func.count()).select_from(UserTrade).where(UserTrade.user_id==uid)) or 0,
            "total_user_accounts":db.scalar(select(func.count()).select_from(UserPaperAccount)) or 0,
            "legacy_account_exists":legacy is not None,
            "legacy_migrated":bool(account.legacy_migrated) if account else None,
            "database_backend":engine.dialect.name,
            "database_persistence_note":("PostgreSQL managed database" if engine.dialect.name=="postgresql" else "SQLite: Railway must mount a persistent Volume at /app/data or data may disappear on redeploy"),
            "legacy_data_recoverable":bool(legacy and (legacy_positions or legacy_trades or abs(float(legacy.balance)-float(legacy.starting_balance))>=0.005 or abs(float(legacy.realized_pnl))>=0.005)),
            "legacy_balance":round(float(legacy.balance),2) if legacy else None,
            "legacy_realized_pnl":round(float(legacy.realized_pnl),2) if legacy else None,
            "legacy_positions":db.scalar(select(func.count()).select_from(Position)) or 0,
            "legacy_trades":db.scalar(select(func.count()).select_from(Trade)) or 0
        }

@app.get("/api/account")
def account(user=Depends(current_user)):return account_snapshot(user["id"])

@app.post("/api/account/reset")
def reset(req:ResetIn,user=Depends(current_user)):
    with SessionLocal() as db:
        uid=user["id"];a=db_account(db,uid);a.starting_balance=req.balance;a.balance=req.balance;a.realized_pnl=0
        a.auto_enabled=False;a.updated_at=int(time.time())
        for p in db.scalars(select(UserPosition).where(UserPosition.user_id==uid)).all():db.delete(p)
        db.query(UserTrade).filter(UserTrade.user_id==uid).delete()
        state=db.get(UserRiskState,uid)
        today=time.strftime("%Y-%m-%d",time.gmtime())
        if state is None:
            db.add(UserRiskState(user_id=uid,day_key=today,day_start_equity=req.balance,
                peak_equity=req.balance,daily_locked=False,overall_failed=False,
                challenge_passed=False,lock_reason="",updated_at=int(time.time())))
        else:
            state.day_key=today;state.day_start_equity=req.balance;state.peak_equity=req.balance
            state.daily_locked=False;state.overall_failed=False;state.challenge_passed=False
            state.lock_reason="";state.updated_at=int(time.time())
        db.commit()
    return account_snapshot(user["id"])

@app.get("/api/quotes")
def quotes():return quotes_meta

def aggregate_candles(rows:list[dict], timeframe:str)->list[dict]:
    seconds={"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400}
    if timeframe not in seconds:raise HTTPException(422,"Unsupported timeframe")
    step=seconds[timeframe];out=[]
    for c in sorted(rows,key=lambda x:int(x["time"])):
        bucket=int(c["time"])//step*step
        if not out or out[-1]["time"]!=bucket:
            out.append({"time":bucket,"open":float(c["open"]),"high":float(c["high"]),
                "low":float(c["low"]),"close":float(c["close"]),"volume":float(c.get("volume",0))})
        else:
            z=out[-1];z["high"]=max(z["high"],float(c["high"]));z["low"]=min(z["low"],float(c["low"]))
            z["close"]=float(c["close"]);z["volume"]+=float(c.get("volume",0))
    return out[-1000:]

def market_structure(rows:list[dict])->dict:
    data=rows[-250:];fvg=[];obs=[]
    for i in range(2,len(data)):
        a,b,c=data[i-2],data[i-1],data[i]
        if float(c["low"])>float(a["high"]):
            fvg.append({"type":"bullish","low":float(a["high"]),"high":float(c["low"]),"time":int(c["time"]),
                "filled":min(float(x["low"]) for x in data[i+1:])<=float(a["high"]) if i+1<len(data) else False})
        if float(c["high"])<float(a["low"]):
            fvg.append({"type":"bearish","low":float(c["high"]),"high":float(a["low"]),"time":int(c["time"]),
                "filled":max(float(x["high"]) for x in data[i+1:])>=float(a["low"]) if i+1<len(data) else False})
    # Confirmed pivot break: last opposite candle before close breaks prior 10-bar swing.
    for i in range(12,len(data)):
        window=data[i-10:i];bar=data[i]
        swing_hi=max(float(x["high"]) for x in window);swing_lo=min(float(x["low"]) for x in window)
        if float(bar["close"])>swing_hi:
            prior=next((x for x in reversed(data[max(0,i-5):i]) if float(x["close"])<float(x["open"])),None)
            if prior:obs.append({"type":"bullish","low":float(prior["low"]),"high":float(prior["open"]),"time":int(prior["time"])})
        elif float(bar["close"])<swing_lo:
            prior=next((x for x in reversed(data[max(0,i-5):i]) if float(x["close"])>float(x["open"])),None)
            if prior:obs.append({"type":"bearish","low":float(prior["open"]),"high":float(prior["high"]),"time":int(prior["time"])})
    return {"fvg":[z for z in fvg[-12:] if not z["filled"]],"order_blocks":obs[-12:]}

@app.get("/api/candles/{symbol}")
def get_candles(symbol:str,timeframe:str="1m"):
    if symbol not in SYMBOLS:raise HTTPException(404,"Unknown symbol")
    rows=candles[symbol]+([current_candle[symbol]] if symbol in current_candle else [])
    rows=[c for c in sanitize_market_candles(symbol,rows) if int(c["time"]) <= int(time.time())+60]
    return aggregate_candles(rows,timeframe)

@app.get("/api/analysis/{symbol}")
def get_analysis(symbol:str,timeframe:str="1m"):
    if symbol not in SYMBOLS:raise HTTPException(404,"Unknown symbol")
    rows=candles[symbol]+([current_candle[symbol]] if symbol in current_candle else [])
    rows=[c for c in sanitize_market_candles(symbol,rows) if int(c["time"]) <= int(time.time())+60]
    return market_structure(aggregate_candles(rows,timeframe))

@app.get("/api/strategies")
def strategies(user=Depends(current_user)):return get_strategy_items(user["id"])

@app.post("/api/orders")
def order(req:OrderIn,user=Depends(current_user)):
    if req.symbol not in prices or not feed_is_fresh(req.symbol):raise HTTPException(503,"No fresh live market price available yet for this symbol")
    with SessionLocal() as db:
        a=db_account(db,user["id"])
        snapshot=account_snapshot(user["id"])
        if snapshot["risk"]["status"]!="ACTIVE":
            raise HTTPException(status_code=403,detail="Funded challenge lock: "+snapshot["risk"]["lock_reason"]+". Daily locks clear on the next UTC day; overall failure requires challenge reset.")
        existing=db.scalars(select(UserPosition).where(UserPosition.user_id==user["id"])).all()
        if len(existing)>=POLICY["max_positions"]:
            raise HTTPException(status_code=403,detail="Maximum open position count reached")
        if req.quantity*prices[req.symbol]*CONTRACT_SIZE[req.symbol]>max(a.balance,0)*MAX_POSITION_NOTIONAL_MULTIPLE:
            raise HTTPException(400,"Paper order notional exceeds 5x account balance")
        entry=prices[req.symbol]
        sl,tp=req.stop_loss,req.take_profit
        if sl is None or tp is None:
            levels=adaptive_levels(req.symbol,req.side,entry,candles[req.symbol])
            if levels is None:raise HTTPException(status_code=503,detail="Not enough candle history to calculate adaptive SL/TP")
            if sl is None:sl=levels[0]
            if tp is None:tp=levels[1]
        if sl is not None and ((req.side=="BUY" and sl>=entry) or (req.side=="SELL" and sl<=entry)):raise HTTPException(status_code=422,detail="Stop loss must be below entry for BUY and above entry for SELL")
        if tp is not None and ((req.side=="BUY" and tp<=entry) or (req.side=="SELL" and tp>=entry)):raise HTTPException(status_code=422,detail="Take profit must be above entry for BUY and below entry for SELL")
        risk_amount=abs(entry-float(sl))*req.quantity*CONTRACT_SIZE[req.symbol]
        risk_limit=max(a.balance,0)*MAX_RISK_PER_TRADE_PCT/100
        if risk_amount>risk_limit+0.01:raise HTTPException(status_code=400,detail=f"Funded-account risk limit exceeded: max risk is ${risk_limit:.2f} (0.5% of balance)")
        p=UserPosition(id=uuid.uuid4().hex,user_id=user["id"],symbol=req.symbol,side=req.side,quantity=req.quantity,
            entry=entry,stop_loss=sl,take_profit=tp,opened_at=int(time.time()),source="manual")
        db.add(p);db.commit()
    return {"accepted":True,"mode":"PAPER_ONLY","position":position_dict(p),"account":account_snapshot(user["id"])}

@app.post("/api/positions/{position_id}/close")
def close(position_id:str,user=Depends(current_user)):
    with SessionLocal() as db:
        p=db.scalar(select(UserPosition).where(UserPosition.id==position_id,UserPosition.user_id==user["id"]))
        if p is None:raise HTTPException(404,"Position not found")
    close_position(user["id"],position_id,"manual")
    return account_snapshot(user["id"])

@app.post("/api/auto")
def auto(req:AutoIn,user=Depends(current_user)):
    if req.enabled:
        item=next((s for s in get_strategy_items(user["id"]) if s["id"]==(req.strategy_id or "STR-001")),None)
        if item is None:raise HTTPException(404,"Strategy not found")
        if not item.get("executable"):raise HTTPException(400,"Strategy is not executable")
        if item["id"] not in SUPPORTED_STRATEGIES and not item["id"].startswith("CUSTOM-"):
            raise HTTPException(400,"Strategy has no implemented execution rules")
        if not any(feed_is_fresh(s) for s in SYMBOLS):
            raise HTTPException(503,"No live market feed is ready. Connect at least one supported feed before enabling auto trading.")
    with SessionLocal() as db:
        a=db_account(db,user["id"])
        if req.enabled:
            risk=account_snapshot(user["id"])["risk"]
            if risk["status"]!="ACTIVE":
                raise HTTPException(status_code=403,detail="Funded challenge lock: "+risk["lock_reason"])
        a.auto_enabled=req.enabled;a.risk_pct=req.risk_pct
        if req.enabled:
            a.active_strategy=req.strategy_id or "STR-001"
            a.active_timeframe=req.timeframe
        db.commit()
    return account_snapshot(user["id"])

@app.post("/api/strategies/custom")
def custom(req:CustomStrategyIn,user=Depends(current_user)):
    if req.fast_ema>=req.slow_ema:raise HTTPException(400,"Fast EMA must be smaller than slow EMA")
    item=UserCustomStrategy(id="CUSTOM-"+uuid.uuid4().hex[:10],user_id=user["id"],name=req.name,symbol=req.symbol,
        fast_ema=req.fast_ema,slow_ema=req.slow_ema,direction=req.direction,created_at=int(time.time()))
    with SessionLocal() as db:db.add(item);db.commit()
    return {"id":item.id,"name":item.name,"category":"Custom",
        "rule_summary":f"EMA {item.fast_ema}/{item.slow_ema}; {item.direction}; {item.symbol}",
        "executable":True,"status":"implemented"}

@app.websocket("/ws/market")
async def ws_market(ws:WebSocket):
    token=ws.query_params.get("access_token")
    if not token:
        await ws.close(code=4401);return
    try:user=verify_access_token(token)
    except HTTPException:
        await ws.close(code=4401);return
    uid=user["id"]
    await ws.accept();clients[ws]=uid
    try:
        await ws.send_json({"quotes":quotes_meta,"feeds":providers.STATUS})
        try:
            await ws.send_json({"account":account_snapshot(uid)})
        except Exception:
            await ws.send_json({"account_error":"Account data temporarily unavailable"})
        while True:await ws.receive_text()
    except WebSocketDisconnect:clients.pop(ws,None)
    except Exception:clients.pop(ws,None)

@app.post("/auth/session")
def establish_browser_session(request:Request,response:Response):
    auth=request.headers.get("authorization","")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401,detail="Sign in required")
    token=auth.split(" ",1)[1].strip()
    verify_access_token(token)
    response.set_cookie("tradex_access_token",token,httponly=True,secure=request.url.scheme=="https",samesite="lax",path="/",max_age=3600)
    return {"ok":True}

@app.post("/auth/logout")
def clear_browser_session(response:Response):
    response.delete_cookie("tradex_access_token",path="/",secure=True,httponly=True,samesite="lax")
    return {"ok":True}

@app.get("/")
def public_home():
    return FileResponse(BASE.parent/"frontend"/"index.html",headers={"Cache-Control":"no-store"})

@app.get("/login")
def public_login():
    return FileResponse(BASE.parent/"frontend"/"login.html",headers={"Cache-Control":"no-store"})

@app.get("/contact")
def public_contact():
    return FileResponse(BASE.parent/"frontend"/"contact.html",headers={"Cache-Control":"no-store"})


@app.post("/api/support")
def create_support_ticket(req:SupportRequestIn,request:Request):
    # Honeypot field catches basic automated form submissions.
    if req.website.strip():
        return {"ok":True,"message":"Your request has been received."}
    email=req.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",email):
        raise HTTPException(status_code=422,detail="Enter a valid email address")
    now=int(time.time())
    with SessionLocal() as db:
        recent=db.scalar(select(func.count(SupportTicket.id)).where(
            SupportTicket.email==email,SupportTicket.created_at>=now-3600)) or 0
        if recent>=5:
            raise HTTPException(status_code=429,detail="Too many requests. Please try again later.")
        ticket=SupportTicket(id=uuid.uuid4().hex[:12].upper(),name=req.name.strip(),
            email=email,category=req.category,subject=req.subject.strip(),message=req.message.strip(),
            status="new",admin_note="",email_sent=False,created_at=now,updated_at=now)
        db.add(ticket);db.commit()
    support_to=os.getenv("SUPPORT_TO_EMAIL","").strip()
    admin_body=(f"New TradeX AI support request\n\nTicket: {ticket.id}\nName: {ticket.name}\n"
        f"Email: {ticket.email}\nCategory: {ticket.category}\nSubject: {ticket.subject}\n\n{ticket.message}")
    delivered=send_support_email(support_to,f"[TradeX AI #{ticket.id}] {ticket.subject}",admin_body) if support_to else False
    send_support_email(ticket.email,f"We received your TradeX AI request #{ticket.id}",
        f"Hi {ticket.name},\n\nWe have received your support request. Your reference is {ticket.id}. "
        "Our team will review it.\n\nTradeX AI Support")
    with SessionLocal() as db:
        saved=db.get(SupportTicket,ticket.id)
        if saved:saved.email_sent=delivered;db.commit()
    return {"ok":True,"ticket_id":ticket.id,"saved":True,"email_sent":delivered,
        "message":"Your request has been saved. "+("The support team has been notified by email." if delivered else "Email notification is not configured yet; your request is safely stored for the support team.")}

@app.get("/api/admin/support")
def list_support_tickets(user=Depends(require_admin)):
    with SessionLocal() as db:
        rows=db.scalars(select(SupportTicket).order_by(desc(SupportTicket.created_at)).limit(200)).all()
        return [{"id":t.id,"name":t.name,"email":t.email,"category":t.category,"subject":t.subject,
            "message":t.message,"status":t.status,"admin_note":t.admin_note,"email_sent":t.email_sent,
            "created_at":t.created_at,"updated_at":t.updated_at} for t in rows]

@app.patch("/api/admin/support/{ticket_id}")
def update_support_ticket(ticket_id:str,req:SupportUpdateIn,user=Depends(require_admin)):
    with SessionLocal() as db:
        ticket=db.get(SupportTicket,ticket_id)
        if ticket is None:raise HTTPException(status_code=404,detail="Support request not found")
        ticket.status=req.status;ticket.admin_note=req.admin_note.strip();ticket.updated_at=int(time.time())
        customer_email=ticket.email;customer_name=ticket.name;ticket_subject=ticket.subject;current_status=ticket.status
        db.commit()
    notified=send_support_email(customer_email,f"TradeX AI support update: {ticket_id}",
        f"Hi {customer_name},\n\nYour support request #{ticket_id} ({ticket_subject}) is now marked: {current_status.replace('_',' ').title()}.\n\nTradeX AI Support")
    return {"ok":True,"id":ticket_id,"status":current_status,"customer_notified":notified}


@app.get("/admin/support")
def admin_support_page(request:Request):
    token=request.cookies.get("tradex_access_token")
    if not token:return RedirectResponse("/login",status_code=303)
    try:user=verify_access_token(token)
    except HTTPException:return RedirectResponse("/login",status_code=303)
    if not user.get("email") or user["email"].lower() not in admin_emails():
        raise HTTPException(status_code=403,detail="Admin access required")
    return FileResponse(BASE.parent/"frontend"/"admin-support.html",headers={"Cache-Control":"no-store"})

@app.get("/dashboard")
def private_dashboard(request:Request):
    token=request.cookies.get("tradex_access_token")
    if not token:
        return RedirectResponse("/login",status_code=303)
    try:
        verify_access_token(token)
    except HTTPException:
        response=RedirectResponse("/login",status_code=303)
        response.delete_cookie("tradex_access_token",path="/",secure=True,httponly=True,samesite="lax")
        return response
    return FileResponse(BASE/"dashboard.html",headers={"Cache-Control":"no-store"})

app.mount("/",StaticFiles(directory=BASE.parent/"frontend",html=True),name="frontend")
