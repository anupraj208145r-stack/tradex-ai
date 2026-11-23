# TradeX AI

Paper-only trading terminal for XAUUSD and BTCUSD. Starter build; demo prices are synthetic, only EMA 9/21 auto logic is implemented. No broker connection or real-money execution.

## Run locally

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000

See project scope and limitations in this README. The initial starter package is available in the conversation download.
