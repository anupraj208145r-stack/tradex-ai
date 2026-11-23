from __future__ import annotations
import asyncio, json, random, time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
CATALOG = json.loads((BASE / "strategies.json").read_text())
START_BALANCE = 10_000.0
state = {
    "balance": START_BALANCE, "equity": START_BALANCE, "realized_pnl": 0.0,
    "positions": [], "history": [], "auto": False, "active_strategy": "STR-001",
    "risk_pct": 1.0, "custom_strategies": []
}
prices = {"XAUUSD": 2350.0, "BTCUSD": 68000.0}
ticks = {"XAUUSD": deque(maxlen=300), "BTCUSD": deque(maxlen=300)}
for symbol, p in prices.items():
    now = int(time.time())
    for i in range(120):
        t = now - (120-i)*60
        o = p * (1 + random.uniform(-0.001,0.001))
        c = o * (1 + random.uniform(-0.0008,0.0008))
        ticks[symbol].append({"time":t, "open":o, "high":max(o,c)*(1+random.random()*0.0004),
                             "low":min(o,c)*(1-random.random()*0.0004), "close":c})
    prices[symbol] = ticks[symbol][-1]["close"]

class OrderIn(BaseModel):
    symbol: Literal["XAUUSD","BTCUSD"]
    side: Literal["BUY","SELL"]
    quantity: float = Field(gt=0, le=100)
    stop_loss: float | None = None
    take_profit: float | None = None

class ResetIn(BaseModel):
    balance: float = Field(gt=0, le=100000000)

class AutoIn(BaseModel):
    enabled: bool
    strategy_id: str | None = None
    risk_pct: float = Field(default=1.0, gt=0, le=5)

class CustomStrategyIn(BaseModel):
    name: str = Field(min_length=3, max_length=60)
    symbol: Literal["XAUUSD","BTCUSD","BOTH"] = "BOTH"
    fast_ema: int = Field(default=9, ge=2, le=100)
    slow_ema: int = Field(default=21, ge=3, le=200)
    direction: Literal["both","long_only","short_only"] = "both"

def ema(values, period):
    if len(values) < period: return None
    k=2/(period+1); result=sum(values[:period])/period
    for v in values[period:]: result=v*k+result*(1-k)
    return result

def mark_equity():
    floating=0.0
    for p in state["positions"]:
        px=prices[p["symbol"]]
        floating += (px-p["entry"])*p["quantity"]*(1 if p["side"]=="BUY" else -1)
    state["equity"] = round(state["balance"]+floating,2)
    return floating

def snapshot():
    floating=mark_equity()
    return {"balance":round(state["balance"],2),"equity":state["equity"],
            "realized_pnl":round(state["realized_pnl"],2),"unrealized_pnl":round(floating,2),
            "positions":state["positions"],"history":state["history"][-100:],
            "auto":state["auto"],"active_strategy":state["active_strategy"],"risk_pct":state["risk_pct"]}

def open_position(order, source="manual"):
    price=prices[order.symbol]
    state["positions"].append({"id":f"P{int(time.time()*1000)}{random.randint(10,99)}",
      "symbol":order.symbol,"side":order.side,"quantity":order.quantity,"entry":price,
      "stop_loss":order.stop_loss,"take_profit":order.take_profit,"opened_at":int(time.time()),
      "source":source})
    return state["positions"][-1]

def close_position(pos, reason="manual"):
    px=prices[pos["symbol"]]
    pnl=(px-pos["entry"])*pos["quantity"]*(1 if pos["side"]=="BUY" else -1)
    state["balance"] += pnl; state["realized_pnl"] += pnl
    state["history"].append({**pos,"exit":px,"closed_at":int(time.time()),"pnl":round(pnl,2),"reason":reason})
    state["positions"]=[p for p in state["positions"] if p["id"]!=pos["id"]]

def evaluate_auto():
    if not state["auto"]: return
    sid=state["active_strategy"]
    strat=next((s for s in CATALOG + state["custom_strategies"] if s["id"]==sid),None)
    if not strat or not strat.get("executable", False): return
    for symbol in ["XAUUSD","BTCUSD"]:
        if any(p["symbol"]==symbol for p in state["positions"]): continue
        closes=[c["close"] for c in ticks[symbol]]
        fast=ema(closes,9); slow=ema(closes,21)
        if fast is None or slow is None: continue
        side="BUY" if fast>slow else "SELL"
        if sid=="STR-001":
            qty=max(0.001, round((state["equity"]*state["risk_pct"]/100)/(prices[symbol]*0.01),3))
            open_position(OrderIn(symbol=symbol,side=side,quantity=qty),source="auto")
    for pos in list(state["positions"]):
        px=prices[pos["symbol"]]
        if pos["stop_loss"] is not None and ((pos["side"]=="BUY" and px<=pos["stop_loss"]) or (pos["side"]=="SELL" and px>=pos["stop_loss"])):
            close_position(pos,"stop_loss")
        elif pos["take_profit"] is not None and ((pos["side"]=="BUY" and px>=pos["take_profit"]) or (pos["side"]=="SELL" and px<=pos["take_profit"])):
            close_position(pos,"take_profit")

async def market_loop():
    while True:
        for symbol in prices:
            prev=prices[symbol]
            # Synthetic demo prices only; never representative of exchange quotes.
            volatility=0.00045 if symbol=="XAUUSD" else 0.0012
            new=max(0.01,prev*(1+random.gauss(0,volatility)))
            prices[symbol]=new
            last=ticks[symbol][-1]
            candle={"time":int(time.time()),"open":last["close"],"high":max(last["close"],new),
                    "low":min(last["close"],new),"close":new}
            if ticks[symbol][-1]["time"]==candle["time"]:
                ticks[symbol][-1]=candle
            else: ticks[symbol].append(candle)
        evaluate_auto()
        await asyncio.sleep(2)

@asynccontextmanager
async def lifespan(app):
    task=asyncio.create_task(market_loop())
    yield
    task.cancel()

app=FastAPI(title="TradeX AI Paper Trading API",version="0.1.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

@app.get("/api/health")
def health():
    return {"ok":True,"mode":"PAPER_ONLY","feed":"DEMO_SYNTHETIC","broker_connected":False}

@app.get("/api/account")
def account(): return snapshot()

@app.post("/api/account/reset")
def reset(req:ResetIn):
    state.update(balance=req.balance,equity=req.balance,realized_pnl=0.0,positions=[],history=[],auto=False)
    return snapshot()

@app.get("/api/quotes")
def quotes():
    return {s:{"symbol":s,"price":round(prices[s],5),"time":int(time.time()),"feed":"DEMO"}
            for s in prices}

@app.get("/api/candles/{symbol}")
def candles(symbol:str):
    if symbol not in ticks: raise HTTPException(404,"Unknown symbol")
    return list(ticks[symbol])

@app.get("/api/strategies")
def strategies(): return CATALOG + state["custom_strategies"]

@app.post("/api/orders")
def order(req:OrderIn):
    pos=open_position(req)
    return {"accepted":True,"mode":"PAPER_ONLY","position":pos,"account":snapshot()}

@app.post("/api/positions/{position_id}/close")
def close(position_id:str):
    pos=next((p for p in state["positions"] if p["id"]==position_id),None)
    if not pos: raise HTTPException(404,"Position not found")
    close_position(pos)
    return snapshot()

@app.post("/api/auto")
def auto(req:AutoIn):
    if req.enabled:
        sid=req.strategy_id or state["active_strategy"]
        strat=next((s for s in CATALOG+state["custom_strategies"] if s["id"]==sid),None)
        if not strat: raise HTTPException(404,"Strategy not found")
        if not strat.get("executable",False):
            raise HTTPException(400,"This strategy is research-only until its rules are verified and encoded.")
        state["active_strategy"]=sid
    state["auto"]=req.enabled; state["risk_pct"]=req.risk_pct
    return snapshot()

@app.post("/api/strategies/custom")
def custom(req:CustomStrategyIn):
    item={"id":f"CUSTOM-{len(state['custom_strategies'])+1:03d}","name":req.name,
          "category":"Custom","rule_summary":f"EMA {req.fast_ema}/{req.slow_ema}; {req.direction}; {req.symbol}",
          "executable":False,"status":"custom_draft","config":req.model_dump()}
    state["custom_strategies"].append(item)
    return item

@app.websocket("/ws/market")
async def ws_market(ws:WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json({"quotes":{s:round(prices[s],5) for s in prices},"account":snapshot()})
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass

from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory=BASE.parent / "frontend", html=True), name="frontend")
