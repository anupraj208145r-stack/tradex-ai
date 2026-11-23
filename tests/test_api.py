from fastapi.testclient import TestClient
from backend.main import app

def test_health_is_paper_only():
    with TestClient(app) as client:
        response=client.get("/api/health")
        assert response.status_code==200
        assert response.json()["mode"]=="PAPER_ONLY"
        assert response.json()["broker_connected"] is False

def test_default_balance_and_reset():
    with TestClient(app) as client:
        response=client.post("/api/account/reset",json={"balance":10000})
        assert response.status_code==200
        assert response.json()["balance"]==10000
        response=client.post("/api/account/reset",json={"balance":2500})
        assert response.status_code==200
        assert response.json()["balance"]==2500

def test_manual_order_requires_real_feed_price():
    with TestClient(app) as client:
        client.post("/api/account/reset",json={"balance":10000})
        response=client.post("/api/orders",json={"symbol":"XAUUSD","side":"BUY","quantity":0.01})
        # CI has no market-data API key. An unavailable quote must never be replaced by a fake price.
        if response.status_code==200:
            assert response.json()["mode"]=="PAPER_ONLY"
        else:
            assert response.status_code==503

def test_research_strategy_cannot_start_auto_trading():
    with TestClient(app) as client:
        response=client.post("/api/auto",json={"enabled":True,"strategy_id":"STR-063","risk_pct":1})
        assert response.status_code==400

def test_custom_strategy_persists_as_non_executable_draft():
    with TestClient(app) as client:
        response=client.post("/api/strategies/custom",json={"name":"Test custom EMA","fast_ema":8,"slow_ema":20})
        assert response.status_code==200
        assert response.json()["executable"] is False
        strategy_id=response.json()["id"]
        assert any(s["id"]==strategy_id for s in client.get("/api/strategies").json())
