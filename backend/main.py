from __future__ import annotations
import asyncio, json, os, time, uuid, re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func

from .db import (init_db, SessionLocal, Candle, UserPaperAccount, UserPosition, UserTrade, UserCustomStrategy, SupportTicket)
from .auth import current_user, verify_access_token
import httpx
from . import providers

BASE=Path(__file__).parent
CATALOG=json.loads((BASE/"strategies.json").read_text())
SYMBOLS=("XAUUSD","BTCUSD")
prices:dict[str,float]={}
quotes_meta:dict[str,dict]={}
candles:dict[str,list[dict]]={s:[] for s in SYMBOLS}
current_candle:dict[str,dict]={}
clients:dict[WebSocket,str]={}
market_lock=asyncio.Lock()
engine_status="starting"


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

def db_account(db,user_id:str):
    account=db.get(UserPaperAccount,user_id)
    if account is None:
        account=UserPaperAccount(user_id=user_id,starting_balance=10000,balance=10000,realized_pnl=0,
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

def account_snapshot(user_id:str):
    with SessionLocal() as db:
        a=db_account(db,user_id)
        positions=[position_dict(p) for p in db.scalars(select(UserPosition).where(UserPosition.user_id==user_id)).all()]
        history=[trade_dict(t) for t in db.scalars(select(UserTrade).where(UserTrade.user_id==user_id).order_by(desc(UserTrade.closed_at)).limit(100)).all()]
        floating=sum((prices.get(p["symbol"],p["entry"])-p["entry"])*p["quantity"]*(1 if p["side"]=="BUY" else -1) for p in positions)
        return {"balance":round(a.balance,2),"equity":round(a.balance+floating,2),
            "realized_pnl":round(a.realized_pnl,2),"unrealized_pnl":round(floating,2),
            "positions":positions,"history":history,"auto":a.auto_enabled,
            "active_strategy":a.active_strategy,"risk_pct":a.risk_pct}

def get_strategy_items(user_id:str):
    with SessionLocal() as db:
        custom=db.scalars(select(UserCustomStrategy).where(UserCustomStrategy.user_id==user_id)).all()
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

def close_position(user_id:str,position_id:str,reason:str):
    with SessionLocal() as db:
        p=db.scalar(select(UserPosition).where(UserPosition.id==position_id,UserPosition.user_id==user_id))
        if p is None:return
        exit_price=prices.get(p.symbol,p.entry)
        pnl=(exit_price-p.entry)*p.quantity*(1 if p.side=="BUY" else -1)
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

def evaluate_auto(symbol:str):
    if any(not feed_is_fresh(s) for s in SYMBOLS):return
    series=candles[symbol]
    closes=[float(c["close"]) for c in series]
    if len(closes)<22:return
    fast_now=ema(closes,9);slow_now=ema(closes,21)
    fast_prev=ema(closes[:-1],9);slow_prev=ema(closes[:-1],21)
    if None in (fast_now,slow_now,fast_prev,slow_prev):return
    side="BUY" if fast_prev<=slow_prev and fast_now>slow_now else "SELL" if fast_prev>=slow_prev and fast_now<slow_now else None
    if side is None:return
    entry=prices.get(symbol)
    if entry is None:return
    with SessionLocal() as db:
        accounts=db.scalars(select(UserPaperAccount).where(UserPaperAccount.auto_enabled.is_(True),UserPaperAccount.active_strategy=="STR-001")).all()
        for a in accounts:
            if db.scalar(select(UserPosition.id).where(UserPosition.user_id==a.user_id,UserPosition.symbol==symbol)) is not None:continue
            stop_distance=entry*0.01
            risk_cash=a.balance*a.risk_pct/100
            qty=min(100.0,max(0.001,round(risk_cash/stop_distance,3)))
            sl=entry-stop_distance if side=="BUY" else entry+stop_distance
            tp=entry+2*stop_distance if side=="BUY" else entry-2*stop_distance
            db.add(UserPosition(id=uuid.uuid4().hex,user_id=a.user_id,symbol=symbol,side=side,quantity=qty,
                entry=entry,stop_loss=sl,take_profit=tp,opened_at=int(time.time()),source="auto"))
        db.commit()

async def publish():
    if not clients:return
    dead=[]
    for ws,user_id in list(clients.items()):
        try:await ws.send_json({"quotes":quotes_meta,"account":account_snapshot(user_id),"feeds":providers.STATUS})
        except Exception:dead.append(ws)
    for ws in dead:clients.pop(ws,None)

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
        # Pause every user's automated strategy on restart.
        db.query(UserPaperAccount).update({UserPaperAccount.auto_enabled:False})
        db.commit()
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

@app.get("/api/me")
def me(user=Depends(current_user)):return {"id":user["id"],"email":user.get("email"),"phone":user.get("phone")}

@app.get("/api/account")
def account(user=Depends(current_user)):return account_snapshot(user["id"])

@app.post("/api/account/reset")
def reset(req:ResetIn,user=Depends(current_user)):
    with SessionLocal() as db:
        uid=user["id"];a=db_account(db,uid);a.starting_balance=req.balance;a.balance=req.balance;a.realized_pnl=0
        a.auto_enabled=False;a.updated_at=int(time.time())
        for p in db.scalars(select(UserPosition).where(UserPosition.user_id==uid)).all():db.delete(p)
        db.query(UserTrade).filter(UserTrade.user_id==uid).delete();db.commit()
    return account_snapshot(user["id"])

@app.get("/api/quotes")
def quotes():return quotes_meta

@app.get("/api/candles/{symbol}")
def get_candles(symbol:str):
    if symbol not in SYMBOLS:raise HTTPException(404,"Unknown symbol")
    return candles[symbol]+([current_candle[symbol]] if symbol in current_candle else [])

@app.get("/api/strategies")
def strategies(user=Depends(current_user)):return get_strategy_items(user["id"])

@app.post("/api/orders")
def order(req:OrderIn,user=Depends(current_user)):
    if req.symbol not in prices or not feed_is_fresh(req.symbol):raise HTTPException(503,"No fresh live market price available yet for this symbol")
    with SessionLocal() as db:
        a=db_account(db,user["id"])
        if req.quantity*prices[req.symbol]>max(a.balance,0)*5:
            raise HTTPException(400,"Paper order notional exceeds 5x account balance")
        p=UserPosition(id=uuid.uuid4().hex,user_id=user["id"],symbol=req.symbol,side=req.side,quantity=req.quantity,
            entry=prices[req.symbol],stop_loss=req.stop_loss,take_profit=req.take_profit,
            opened_at=int(time.time()),source="manual")
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
        if item["id"]!="STR-001":raise HTTPException(400,"Only EMA 9/21 is implemented in this milestone")
        if any(not feed_is_fresh(s) for s in SYMBOLS):
            raise HTTPException(503,"Both live feeds must be connected before enabling auto trading")
    with SessionLocal() as db:
        a=db_account(db,user["id"]);a.auto_enabled=req.enabled;a.risk_pct=req.risk_pct
        if req.enabled:a.active_strategy=req.strategy_id or "STR-001"
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
        "executable":False,"status":"custom_draft"}

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
        await ws.send_json({"quotes":quotes_meta,"account":account_snapshot(uid),"feeds":providers.STATUS})
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
        db.commit()
        return {"ok":True,"id":ticket.id,"status":ticket.status}


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
