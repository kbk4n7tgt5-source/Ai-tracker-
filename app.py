from flask import Flask, jsonify, render_template, request
from collections import deque
from statistics import mean
from datetime import datetime
import os
import time
import requests

app = Flask(__name__, template_folder=".")

FAST_WINDOW = 6
SLOW_WINDOW = 20
NEWS_REFRESH_SECONDS = 15 * 60
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "").strip()

running = True
signals = []


def new_asset(asset_type):
    return {
        "type": asset_type,
        "price": 0,
        "prices": deque(maxlen=SLOW_WINDOW),
        "signal": "WAIT",
        "news_sentiment": "UNKNOWN",
        "news_score": 0,
        "headlines": [],
        "last_news_update": 0,
        "error": "",
    }


assets = {
    "AAPL": new_asset("stock"),
    "NVDA": new_asset("stock"),
    "TSLA": new_asset("stock"),
    "BTC-USD": new_asset("crypto"),
    "ETH-USD": new_asset("crypto"),
    "SOL-USD": new_asset("crypto"),
}


def get_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    response = requests.get(
        url,
        params={"interval": "1m", "range": "1d"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    price = result["meta"].get("regularMarketPrice")

    if price is None:
        closes = result["indicators"]["quote"][0]["close"]
        valid = [value for value in closes if value is not None]
        if not valid:
            raise ValueError("No price available")
        price = valid[-1]

    return round(float(price), 4)


def get_news_sentiment(symbol, asset_type):
    if not ALPHA_VANTAGE_KEY:
        return {"sentiment": "UNKNOWN", "score": 0, "headlines": []}

    try:
        params = {
            "function": "NEWS_SENTIMENT",
            "limit": 10,
            "apikey": ALPHA_VANTAGE_KEY,
        }
        if asset_type == "crypto":
            params["blockchain"] = symbol.split("-")[0]
        else:
            params["tickers"] = symbol

        response = requests.get(
            "https://www.alphavantage.co/query", params=params, timeout=12
        )
        response.raise_for_status()
        data = response.json()

        if data.get("Information") or data.get("Note"):
            raise RuntimeError(data.get("Information") or data.get("Note"))

        feed = data.get("feed") or []
        scores = []
        headlines = []

        for article in feed[:10]:
            try:
                score = float(article.get("overall_sentiment_score", 0))
            except (TypeError, ValueError):
                score = 0
            scores.append(score)
            headlines.append(
                {
                    "title": article.get("title", "Market update"),
                    "url": article.get("url", ""),
                    "source": article.get("source", ""),
                    "summary": article.get("summary", ""),
                    "score": round(score, 3),
                    "symbol": symbol,
                }
            )

        if not scores:
            return {"sentiment": "UNKNOWN", "score": 0, "headlines": []}

        average = sum(scores) / len(scores)
        sentiment = "POSITIVE" if average >= 0.15 else "NEGATIVE" if average <= -0.15 else "NEUTRAL"
        return {
            "sentiment": sentiment,
            "score": round(average, 3),
            "headlines": headlines[:5],
        }
    except Exception as exc:
        return {
            "sentiment": "UNKNOWN",
            "score": 0,
            "headlines": [],
            "error": str(exc),
        }


def calculate_signal(asset):
    prices = list(asset["prices"])
    if len(prices) < SLOW_WINDOW:
        return "WAIT"
    fast_average = mean(prices[-FAST_WINDOW:])
    slow_average = mean(prices)
    if fast_average > slow_average * 1.0015:
        return "BUY"
    if fast_average < slow_average * 0.9985:
        return "SELL"
    return "WAIT"


def update_asset(symbol, asset):
    try:
        price = get_price(symbol)
        asset["price"] = price
        asset["prices"].append(price)
        asset["error"] = ""

        now = time.time()
        if now - asset["last_news_update"] >= NEWS_REFRESH_SECONDS:
            news = get_news_sentiment(symbol, asset["type"])
            if news.get("headlines"):
                asset["headlines"] = news["headlines"]
                asset["news_sentiment"] = news["sentiment"]
                asset["news_score"] = news["score"]
            elif not asset["headlines"]:
                asset["news_sentiment"] = news.get("sentiment", "UNKNOWN")
                asset["news_score"] = news.get("score", 0)
            asset["last_news_update"] = now

        new_signal = calculate_signal(asset)
        if new_signal in ("BUY", "SELL") and new_signal != asset["signal"]:
            signals.insert(
                0,
                {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "symbol": symbol,
                    "signal": new_signal,
                    "price": price,
                },
            )
            del signals[50:]
        asset["signal"] = new_signal
    except Exception as exc:
        asset["error"] = str(exc)


def serialize_asset(asset):
    return {
        "type": asset["type"],
        "price": asset["price"],
        "signal": asset["signal"],
        "news_sentiment": asset["news_sentiment"],
        "news_score": asset["news_score"],
        "headlines": asset["headlines"],
        "error": asset["error"],
        "samples": len(asset["prices"]),
    }


def combined_news():
    articles = []
    seen = set()
    for asset in assets.values():
        for article in asset["headlines"]:
            key = article.get("url") or article.get("title")
            if key and key not in seen:
                seen.add(key)
                articles.append(article)
    return articles[:20]


def ai_market_view():
    return [
        {
            "symbol": symbol,
            "outlook": (
                "BULLISH" if asset["signal"] == "BUY"
                else "BEARISH" if asset["signal"] == "SELL"
                else "NEUTRAL"
            ),
            "news_sentiment": asset["news_sentiment"],
            "sentiment_score": asset["news_score"],
            "signal": asset["signal"],
        }
        for symbol, asset in assets.items()
    ]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def status():
    if running:
        for symbol, asset in assets.items():
            update_asset(symbol, asset)
    return jsonify(
        {
            "running": running,
            "assets": {symbol: serialize_asset(asset) for symbol, asset in assets.items()},
            "news": combined_news(),
            "ai_market_view": ai_market_view(),
            "signals": signals[:20],
        }
    )


@app.route("/api/add", methods=["POST"])
def add_asset():
    data = request.get_json(silent=True) or {}
    symbol = str(data.get("symbol", "")).upper().strip()
    asset_type = str(data.get("type", "stock")).lower().strip()
    if not symbol:
        return jsonify({"error": "Symbol required"}), 400
    if asset_type not in ("stock", "crypto"):
        asset_type = "stock"
    if asset_type == "crypto":
        symbol = symbol.replace("/", "-")
        if "-" not in symbol:
            symbol += "-USD"
    if symbol not in assets:
        assets[symbol] = new_asset(asset_type)
    return jsonify({"ok": True, "symbol": symbol})


@app.route("/api/remove", methods=["POST"])
def remove_asset():
    data = request.get_json(silent=True) or {}
    symbol = str(data.get("symbol", "")).upper().strip()
    assets.pop(symbol, None)
    return jsonify({"ok": True})


@app.route("/api/start", methods=["POST"])
def start():
    global running
    running = True
    return jsonify({"running": running})


@app.route("/api/stop", methods=["POST"])
def stop():
    global running
    running = False
    return jsonify({"running": running})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "alpha_key_loaded": bool(ALPHA_VANTAGE_KEY)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
