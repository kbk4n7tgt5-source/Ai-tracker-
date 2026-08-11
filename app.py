from flask import Flask, jsonify, render_template, request
from collections import deque
from statistics import mean
from datetime import datetime
import requests
import os

app = Flask(__name__, template_folder=".")

FAST_WINDOW = 6
SLOW_WINDOW = 20

running = False
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY")

assets = {
    "BTC-USD": {
        "type": "crypto",
        "prices": deque(maxlen=SLOW_WINDOW),
        "price": 0,
        "signal": "WAIT",
        "error": ""
    },
    "ETH-USD": {
        "type": "crypto",
        "prices": deque(maxlen=SLOW_WINDOW),
        "price": 0,
        "signal": "WAIT",
        "error": ""
    },
    "AAPL": {
        "type": "stock",
        "prices": deque(maxlen=SLOW_WINDOW),
        "price": 0,
        "signal": "WAIT",
        "error": ""
    },
    "NVDA": {
        "type": "stock",
        "prices": deque(maxlen=SLOW_WINDOW),
        "price": 0,
        "signal": "WAIT",
        "error": ""
    }
}

signals = []
def get_news_sentiment(symbol, asset_type):
    if not ALPHA_VANTAGE_KEY:
        return {
            "sentiment": "UNKNOWN",
            "score": 0,
            "headlines": []
        }

    if asset_type == "crypto":
        ticker = symbol.split("-")[0]
        params = {
            "function": "NEWS_SENTIMENT",
            "blockchain": ticker,
            "limit": 20,
            "apikey": ALPHA_VANTAGE_KEY
        }
    else:
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": symbol,
            "limit": 20,
            "apikey": ALPHA_VANTAGE_KEY
        }

    try:
        r = requests.get(
            "https://www.alphavantage.co/query",
            params=params,
            timeout=10
        )
        r.raise_for_status()
        data = r.json()

        feed = data.get("feed", [])

        if not feed:
            return {
                "sentiment": "NEUTRAL",
                "score": 0,
                "headlines": []
            }

        scores = []
        headlines = []

        for article in feed[:10]:
            score = float(article.get("overall_sentiment_score", 0))
            scores.append(score)

            headlines.append({
                "title": article.get("title", ""),
                "source": article.get("source", ""),
                "score": round(score, 3)
            })

        avg_score = sum(scores) / len(scores)

        if avg_score >= 0.15:
            sentiment = "POSITIVE"
        elif avg_score <= -0.15:
            sentiment = "NEGATIVE"
        else:
            sentiment = "NEUTRAL"

        return {
            "sentiment": sentiment,
            "score": round(avg_score, 3),
            "headlines": headlines[:5]
        }

    except Exception as exc:
        return {
            "sentiment": "UNKNOWN",
            "score": 0,
            "headlines": [],
            "error": str(exc)
        }

def get_crypto_price(symbol):
    product = symbol.replace("/", "-").upper()

    url = f"https://api.exchange.coinbase.com/products/{product}/ticker"

    r = requests.get(
        url,
        headers={"User-Agent": "AI-Market-Tracker"},
        timeout=8
    )

    r.raise_for_status()
    data = r.json()

    return float(data["price"])


def get_stock_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    r = requests.get(
        url,
        params={
            "interval": "1m",
            "range": "1d"
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=8
    )

    r.raise_for_status()

    data = r.json()
    result = data["chart"]["result"][0]

    price = result["meta"].get("regularMarketPrice")

    if price is None:
        closes = result["indicators"]["quote"][0]["close"]
        closes = [x for x in closes if x is not None]
        price = closes[-1]

    return float(price)


def calculate_signal(asset):
    prices = list(asset["prices"])

    if len(prices) < SLOW_WINDOW:
        return "WAIT"

    fast_avg = mean(prices[-FAST_WINDOW:])
    slow_avg = mean(prices)

    if fast_avg > slow_avg * 1.0015:
        return "BUY"

    if fast_avg < slow_avg * 0.9985:
        return "SELL"

    return "HOLD"


def update_asset(symbol, asset):
    try:
        if asset["type"] == "crypto":
            price = get_crypto_price(symbol)
        else:
            price = get_stock_price(symbol)

        asset["price"] = price
        asset["prices"].append(price)
        asset["error"] = ""

        new_signal = calculate_signal(asset)

        if new_signal in ("BUY", "SELL") and new_signal != asset["signal"]:
            signals.insert(0, {
                "time": datetime.now().strftime("%H:%M:%S"),
                "symbol": symbol,
                "signal": new_signal,
                "price": price
            })

            del signals[50:]

        asset["signal"] = new_signal

    except Exception as exc:
        asset["error"] = str(exc)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def status():
    if running:
        for symbol, asset in assets.items():
            update_asset(symbol, asset)

    output = {}

    for symbol, asset in assets.items():
        output[symbol] = {
            "type": asset["type"],
            "price": asset["price"],
            "signal": asset["signal"],
            "error": asset["error"]
        }

    return jsonify({
        "running": running,
        "mode": "LIVE_DATA_ALERT_ONLY",
        "assets": output,
        "signals": signals
    })


@app.route("/api/add", methods=["POST"])
def add_asset():
    data = request.get_json()

    symbol = data.get("symbol", "").upper().strip()
    asset_type = data.get("type", "").lower().strip()

    if not symbol:
        return jsonify({"ok": False, "error": "Symbol required"}), 400

    if asset_type not in ("stock", "crypto"):
        return jsonify({
            "ok": False,
            "error": "Type must be stock or crypto"
        }), 400

    assets[symbol] = {
        "type": asset_type,
        "prices": deque(maxlen=SLOW_WINDOW),
        "price": 0,
        "signal": "WAIT",
        "error": ""
    }

    return jsonify({"ok": True})


@app.route("/api/remove", methods=["POST"])
def remove_asset():
    data = request.get_json()
    symbol = data.get("symbol", "").upper().strip()

    if symbol in assets:
        del assets[symbol]

    return jsonify({"ok": True})


@app.route("/api/start", methods=["POST"])
def start():
    global running
    running = True
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def stop():
    global running
    running = False
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
