from fastapi.testclient import TestClient
from backend.main import app

def test_health_is_public_and_paper_only():
    with TestClient(app) as client:
        response=client.get("/api/health")
        assert response.status_code==200
        assert response.json()["mode"]=="PAPER_ONLY"
        assert response.json()["broker_connected"] is False

def test_account_requires_supabase_session():
    protected=[
        ("GET","/api/me",None),
        ("GET","/api/account",None),
        ("POST","/api/account/reset",{"balance":10000}),
        ("GET","/api/strategies",None),
        ("POST","/api/orders",{"symbol":"XAUUSD","side":"BUY","quantity":0.01}),
        ("POST","/api/auto",{"enabled":False,"risk_pct":1}),
        ("POST","/api/strategies/custom",{"name":"Test strategy","fast_ema":8,"slow_ema":20}),
    ]
    with TestClient(app) as client:
        for method,path,payload in protected:
            response=client.request(method,path,json=payload)
            assert response.status_code==401, (path,response.status_code,response.text)

def test_public_market_data_does_not_require_login():
    with TestClient(app) as client:
        assert client.get("/api/quotes").status_code==200
        assert client.get("/api/candles/XAUUSD").status_code==200

def test_research_strategy_catalog_is_not_executable():
    import json
    from pathlib import Path
    catalog=json.loads((Path(__file__).parents[1]/"backend"/"strategies.json").read_text())
    research=[item for item in catalog if item["status"]=="research_required"]
    assert research
    assert all(item["executable"] is False for item in research)
