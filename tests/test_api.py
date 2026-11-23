from fastapi.testclient import TestClient
from backend.main import app

def test_health_is_paper_only():
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["mode"] == "PAPER_ONLY"
        assert response.json()["broker_connected"] is False

def test_default_balance_and_reset():
    with TestClient(app) as client:
        assert client.get("/api/account").json()["balance"] == 10000
        response = client.post("/api/account/reset", json={"balance": 2500})
        assert response.status_code == 200
        assert response.json()["balance"] == 2500

def test_manual_paper_order():
    with TestClient(app) as client:
        client.post("/api/account/reset", json={"balance": 10000})
        response = client.post("/api/orders", json={"symbol": "XAUUSD", "side": "BUY", "quantity": 0.01})
        assert response.status_code == 200
        assert response.json()["mode"] == "PAPER_ONLY"

def test_research_strategy_cannot_start_auto_trading():
    with TestClient(app) as client:
        response = client.post("/api/auto", json={"enabled": True, "strategy_id": "STR-063", "risk_pct": 1})
        assert response.status_code == 400
