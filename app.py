
from flask import Flask, jsonify, render_template
from datetime import datetime
from collections import deque
from statistics import mean
import requests

app = Flask(__name__)

PRODUCT_ID = "BTC-USD"
FAST_WINDOW = 6
SLOW_WINDOW = 20

prices = deque(maxlen=SLOW_WINDOW)

state = {
    "running": False,
    "mode": "LIVE_DATA_ALERT_ONLY",
    "symbol": "BTC/USD",
    "last_price": 0.0,
    "bid": 0.0,
    "ask": 0.0,
    "signal": "WAIT",
    "signals": [],
    "error": ""
}

def get_live_coinbase_price():
    url = f"https://api.exchange.coinbase.com/products/{PRODUCT_ID}/ticker"
    r = requests.get(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AI-Trader-Live-Alerts/1.0",
            "Cache-Control": "no-cache"
        },
        timeout=8
    )
    r.raise_for_status()
    data = r.json()
    return {
        "price": float(data["price"]),
        "bid": float(data["bid"]),
        "ask": float(data["ask"])
    }

def calculate_signal():
    if len(prices) < SLOW_WINDOW:
        return "WAIT"

    p = list(prices)
    fast_avg = mean(p[-FAST_WINDOW:])
    slow_avg = mean(p)

    if fast_avg > slow_avg * 1.0015:
        return "BUY"
    if fast_avg < slow_avg * 0.9985:
        return "SELL"
    return "HOLD"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def status():
    if state["running"]:
        try:
            quote = get_live_coinbase_price()
            state["last_price"] = quote["price"]
            state["bid"] = quote["bid"]
            state["ask"] = quote["ask"]
            state["error"] = ""

            prices.append(quote["price"])
            new_signal = calculate_signal()

            if new_signal in ("BUY", "SELL") and new_signal != state["signal"]:
                state["signals"].insert(0, {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "signal": new_signal,
                    "symbol": state["symbol"],
                    "price": quote["price"]
                })
                state["signals"] = state["signals"][:20]

            state["signal"] = new_signal

        except Exception as exc:
            state["error"] = str(exc)
            state["signal"] = "ERROR"

    return jsonify(state)

@app.route("/api/start", methods=["POST"])
def start():
    state["running"] = True
    state["error"] = ""
    return jsonify({"ok": True})

@app.route("/api/stop", methods=["POST"])
def stop():
    state["running"] = False
    state["signal"] = "WAIT"
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
