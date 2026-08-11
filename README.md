# AI Trader Live Alerts

This replaces the fake/random BTC price with live BTC/USD ticker data.

It shows live price, bid, ask, and basic BUY/SELL/HOLD/WAIT alerts.

It does NOT submit orders or automatically trade real money.

Local:
pip install -r requirements.txt
python app.py

Cloud start command:
gunicorn app:app
