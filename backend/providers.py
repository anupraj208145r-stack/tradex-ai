from __future__ import annotations
import asyncio, json, os, random, time
from collections.abc import Awaitable, Callable
from urllib.parse import quote
import httpx
import websockets

TickCallback = Callable[[str, float, int, str], Awaitable[None]]
STATUS = {"BTCUSD":"starting", "XAUUSD":"missing_credentials" if not os.getenv("TWELVEDATA_API_KEY") else "starting"}
LAST_ERROR = {"BTCUSD":None,"XAUUSD":None}

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
                await ws.send(json.dumps({"type":"subscribe","product_ids":["BTC-USD"],"channel":"ticker"}))
                STATUS["BTCUSD"]="connected"; LAST_ERROR["BTCUSD"]=None; delay=1
                async for raw in ws:
                    message=json.loads(raw)
                    for event in message.get("events",[]):
                        for ticker in event.get("tickers",[]):
                            if ticker.get("product_id")=="BTC-USD" and ticker.get("price"):
                                await on_tick("BTCUSD",float(ticker["price"]),int(time.time()),"coinbase")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            STATUS["BTCUSD"]="reconnecting"; LAST_ERROR["BTCUSD"]=str(exc)[:240]
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
                STATUS["XAUUSD"]="connected"; LAST_ERROR["XAUUSD"]=None; delay=1
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
            STATUS["XAUUSD"]="reconnecting"; LAST_ERROR["XAUUSD"]=str(exc)[:240]
            await asyncio.sleep(delay+random.random()); delay=min(delay*2,30)
