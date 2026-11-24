from __future__ import annotations
import asyncio, json, os, random, time
from collections.abc import Awaitable, Callable
from urllib.parse import quote
import httpx
import websockets

TickCallback = Callable[[str, float, int, str], Awaitable[None]]
STATUS = {"BTCUSD":"starting", "XAUUSD":"missing_credentials" if not os.getenv("TWELVEDATA_API_KEY") else "starting"}
LAST_ERROR = {"BTCUSD":None,"XAUUSD":None}
LAST_TICK_AT = {"BTCUSD":0.0,"XAUUSD":0.0}

def safe_error(exc:Exception)->str:
    message=str(exc)
    secret=os.getenv("TWELVEDATA_API_KEY")
    if secret:message=message.replace(secret,"[REDACTED]")
    return message[:240]

async def history(symbol: str) -> list[dict]:
    timeout=httpx.Timeout(15.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if symbol == "BTCUSD":
            response=await client.get("https://api.exchange.coinbase.com/products/BTC-USD/candles",
                                      params={"granularity":60})
            response.raise_for_status()
            rows=response.json()
            return [{"time":int(r[0]),"low":float(r[1]),"high":float(r[2]),
                     "open":float(r[3]),"close":float(r[4]),"volume":float(r[5]),
                     "source":"coinbase"} for r in reversed(rows)]
        api_key=os.getenv("TWELVEDATA_API_KEY")
        if not api_key: return []
        response=await client.get("https://api.twelvedata.com/time_series",
            params={"symbol":"XAU/USD","interval":"1min","outputsize":300,"apikey":api_key})
        response.raise_for_status()
        payload=response.json()
        if payload.get("status")=="error" or "values" not in payload:
            raise RuntimeError(payload.get("message","Twelve Data history unavailable"))
        from datetime import datetime, timezone
        values=[]
        for item in reversed(payload["values"]):
            dt=datetime.fromisoformat(item["datetime"].replace("Z","+00:00"))
            values.append({"time":int(dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp()),
                "open":float(item["open"]),"high":float(item["high"]),
                "low":float(item["low"]),"close":float(item["close"]),
                "volume":float(item.get("volume") or 0),"source":"twelvedata"})
        return values

async def coinbase_stream(on_tick: TickCallback):
    delay=1
    while True:
        try:
            STATUS["BTCUSD"]="connecting"
            async with websockets.connect("wss://advanced-trade-ws.coinbase.com",
                    ping_interval=20,ping_timeout=20,close_timeout=5) as ws:
                await ws.send(json.dumps({"type":"subscribe","product_ids":["BTC-USD"],"channel":"ticker_batch"}))
                await ws.send(json.dumps({"type":"subscribe","channel":"heartbeats"}))
                STATUS["BTCUSD"]="awaiting_ticks"; LAST_ERROR["BTCUSD"]=None; delay=1
                async for raw in ws:
                    message=json.loads(raw)
                    if message.get("type")=="error" or message.get("channel")=="error":
                        raise RuntimeError(message.get("message") or message.get("reason") or "Coinbase WebSocket error")
                    for event in message.get("events",[]):
                        for ticker in event.get("tickers",[]):
                            if ticker.get("product_id")=="BTC-USD" and ticker.get("price"):
                                await on_tick("BTCUSD",float(ticker["price"]),int(time.time()),"coinbase")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            STATUS["BTCUSD"]="reconnecting"; LAST_ERROR["BTCUSD"]=safe_error(exc)
            import logging; logging.getLogger("tradex.market").warning("BTCUSD WebSocket reconnect: %s",LAST_ERROR["BTCUSD"])
            await asyncio.sleep(delay+random.random()); delay=min(delay*2,30)

async def gold_stream(on_tick: TickCallback):
    api_key=os.getenv("TWELVEDATA_API_KEY")
    if not api_key:
        STATUS["XAUUSD"]="missing_credentials"
        return
    url="wss://ws.twelvedata.com/v1/quotes/price?apikey="+quote(api_key)
    delay=1
    while True:
        try:
            STATUS["XAUUSD"]="connecting"
            async with websockets.connect(url,ping_interval=20,ping_timeout=20,close_timeout=5) as ws:
                await ws.send(json.dumps({"action":"subscribe","params":{"symbols":"XAU/USD"}}))
                async def heartbeat():
                    while True:
                        await asyncio.sleep(10)
                        await ws.send(json.dumps({"action":"heartbeat"}))
                heartbeat_task=asyncio.create_task(heartbeat())
                STATUS["XAUUSD"]="awaiting_ticks"; LAST_ERROR["XAUUSD"]=None; delay=1
                try:
                    async for raw in ws:
                        message=json.loads(raw)
                        if message.get("event")=="price" and message.get("symbol") in ("XAU/USD","XAUUSD"):
                            await on_tick("XAUUSD",float(message["price"]),
                                int(message.get("timestamp") or time.time()),"twelvedata")
                        elif message.get("status")=="error" or message.get("event")=="error":
                            raise RuntimeError(message.get("message") or str(message))
                finally:
                    heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task,return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            STATUS["XAUUSD"]="reconnecting"; LAST_ERROR["XAUUSD"]=safe_error(exc)
            import logging; logging.getLogger("tradex.market").warning("XAUUSD WebSocket reconnect: %s",LAST_ERROR["XAUUSD"])
            await asyncio.sleep(delay+random.random()); delay=min(delay*2,30)

async def rest_quote(symbol: str) -> float:
    timeout=httpx.Timeout(8.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if symbol=="BTCUSD":
            response=await client.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker")
            response.raise_for_status()
            payload=response.json()
            value=float(payload["price"])
        else:
            api_key=os.getenv("TWELVEDATA_API_KEY")
            if not api_key:
                raise RuntimeError("TWELVEDATA_API_KEY is not configured")
            response=await client.get("https://api.twelvedata.com/price",
                params={"symbol":"XAU/USD","apikey":api_key})
            response.raise_for_status()
            payload=response.json()
            if payload.get("status")=="error" or "price" not in payload:
                raise RuntimeError(payload.get("message","Twelve Data price unavailable"))
            value=float(payload["price"])
        if not (value>0 and value<float("inf")):
            raise RuntimeError("Provider returned an invalid price")
        return value

async def rest_fallback(symbol: str, on_tick: TickCallback):
    interval=5 if symbol=="BTCUSD" else 12
    stale_after=12 if symbol=="BTCUSD" else 25
    while True:
        try:
            if time.time()-LAST_TICK_AT[symbol] > stale_after:
                price=await rest_quote(symbol)
                await on_tick(symbol,price,int(time.time()),
                    "coinbase-rest" if symbol=="BTCUSD" else "twelvedata-rest")
                LAST_ERROR[symbol]=None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LAST_ERROR[symbol]=safe_error(exc)
            import logging; logging.getLogger("tradex.market").warning("%s REST fallback: %s",symbol,LAST_ERROR[symbol])
        await asyncio.sleep(interval)
