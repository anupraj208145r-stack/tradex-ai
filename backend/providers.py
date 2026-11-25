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
    # Keep credentials out of the URL/logs. Twelve Data also documents
    # X-TD-APIKEY as a supported WebSocket authentication header.
    url="wss://ws.twelvedata.com/v1/quotes/price"
    auth_headers={"X-TD-APIKEY":api_key}
    delay=2
    while True:
        heartbeat_at=time.monotonic()+10
        try:
            STATUS["XAUUSD"]="connecting"
            async with websockets.connect(
                url, additional_headers=auth_headers,
                ping_interval=None, close_timeout=5, open_timeout=15,
                max_queue=32
            ) as ws:
                await ws.send(json.dumps({
                    "action":"subscribe",
                    "params":{"symbols":"XAU/USD"}
                }))
                STATUS["XAUUSD"]="awaiting_ticks"
                LAST_ERROR["XAUUSD"]=None
                subscribed=False
                delay=2
                while True:
                    # Twelve Data recommends an application heartbeat every ~10s.
                    timeout=max(0.1,heartbeat_at-time.monotonic())
                    try:
                        raw=await asyncio.wait_for(ws.recv(),timeout=timeout)
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"action":"heartbeat"}))
                        heartbeat_at=time.monotonic()+10
                        continue
                    message=json.loads(raw)
                    event=message.get("event")
                    if event=="subscribe-status":
                        failures=message.get("fails") or []
                        success=message.get("success") or []
                        if message.get("status")!="ok" or failures or not any(
                            item.get("symbol") in ("XAU/USD","XAUUSD") for item in success
                        ):
                            raise RuntimeError(
                                "Twelve Data subscription not accepted: "+
                                json.dumps({"success":success,"fails":failures})[:180]
                            )
                        subscribed=True
                        STATUS["XAUUSD"]="subscribed_waiting_ticks"
                    elif event=="price":
                        if message.get("symbol") not in ("XAU/USD","XAUUSD"):
                            continue
                        price=float(message["price"])
                        timestamp=int(message.get("timestamp") or time.time())
                        await on_tick("XAUUSD",price,timestamp,"twelvedata")
                        STATUS["XAUUSD"]="connected"
                        LAST_ERROR["XAUUSD"]=None
                    elif message.get("status")=="error" or event=="error":
                        raise RuntimeError("Twelve Data error: "+json.dumps(message)[:180])
                    # Ignore heartbeat/status messages; price events alone make feed live.
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Preserve close code/reason; the generic websockets string alone hides it.
            detail=safe_error(exc)
            close_code=getattr(exc,"code",None)
            close_reason=getattr(exc,"reason",None)
            if close_code is not None:
                detail=f"{type(exc).__name__}: close_code={close_code}, reason={close_reason!r}"
            STATUS["XAUUSD"]="reconnecting"
            LAST_ERROR["XAUUSD"]=detail[:240]
            import logging
            logging.getLogger("tradex.market").warning(
                "XAUUSD WebSocket disconnected (subscribed=%s): %s",
                locals().get("subscribed",False), LAST_ERROR["XAUUSD"]
            )
            await asyncio.sleep(delay+random.random())
            delay=min(delay*2,60)
        else:
            # A clean server close still needs a paced reconnect.
            STATUS["XAUUSD"]="reconnecting"
            LAST_ERROR["XAUUSD"]="Twelve Data closed the WebSocket connection"
            await asyncio.sleep(delay+random.random())
            delay=min(delay*2,60)

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
    # Twelve Data Basic has a small per-minute API budget. Keep Gold polling
    # conservative and back off after provider throttling instead of retrying.
    base_interval=5 if symbol=="BTCUSD" else 60
    stale_after=12 if symbol=="BTCUSD" else 60
    interval=base_interval
    while True:
        try:
            if time.time()-LAST_TICK_AT[symbol] > stale_after:
                price=await rest_quote(symbol)
                await on_tick(symbol,price,int(time.time()),
                    "coinbase-rest" if symbol=="BTCUSD" else "twelvedata-rest")
                LAST_ERROR[symbol]=None
                interval=base_interval
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LAST_ERROR[symbol]=safe_error(exc)
            import logging; logging.getLogger("tradex.market").warning("%s REST fallback: %s",symbol,LAST_ERROR[symbol])
            if "429" in str(exc) or "Too Many Requests" in str(exc):
                interval=min(max(interval*2,base_interval),300)
        await asyncio.sleep(interval)
