from flask import Flask, jsonify, render_template, request
from collections import deque
from statistics import mean
from datetime import datetime
import requests
import os

app = Flask(__name__, template_folder="templates")

FAST_WINDOW = 6
SLOW_WINDOW = 20

running = True
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

assets = {
    "AAPL": {
        "type": "stock",
        "price": 0,
        "prices": deque(maxlen=SLOW_WINDOW),
        "signal": "WAIT",
        "news_sentiment": "UNKNOWN",
        "news_score": 0,
        "headlines": [],
        "error": ""
    },
    "NVDA": {
        "type": "stock",
        "price": 0,
        "prices": deque(maxlen=SLOW_WINDOW),
        "signal": "WAIT",
        "news_sentiment": "UNKNOWN",
        "news_score": 0,
        "headlines": [],
        "error": ""
    },
    "TSLA": {
        "type": "stock",
        "price": 0,
        "prices": deque(maxlen=SLOW_WINDOW),
        "signal": "WAIT",
        "news_sentiment": "UNKNOWN",
        "news_score": 0,
        "headlines": [],
        "error": ""
    },
    "BTC-USD": {
        "type": "crypto",
        "price": 0,
        "prices": deque(maxlen=SLOW_WINDOW),
        "signal": "WAIT",
        "news_sentiment": "UNKNOWN",
        "news_score": 0,
        "headlines": [],
        "error": ""
    },
    "ETH-USD": {
        "type": "crypto",
        "price": 0,
        "prices": deque(maxlen=SLOW_WINDOW),
        "signal": "WAIT",
        "news_sentiment": "UNKNOWN",
        "news_score": 0,
        "headlines": [],
        "error": ""
    },
    "SOL-USD": {
        "type": "crypto",
        "price": 0,
        "prices": deque(maxlen=SLOW_WINDOW),
        "signal": "WAIT",
        "news_sentiment": "UNKNOWN",
        "news_score": 0,
        "headlines": [],
        "error": ""
    }
}

signals = []


def get_price(symbol):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + symbol
        + "?interval=1m&range=1d"
    )

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    result = data["chart"]["result"][0]

    price = result["meta"].get("regularMarketPrice")

    if price is None:
        closes = result["indicators"]["quote"][0]["close"]
        valid = [x for x in closes if x is not None]

        if not valid:
            raise ValueError("No price available")

        price = valid[-1]

    return round(float(price), 4)


def get_news_sentiment(symbol, asset_type):
    if not ALPHA_VANTAGE_KEY:
        return {
            "sentiment": "UNKNOWN",
            "score": 0,
            "headlines": []
        }

    try:
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

        response = requests.get(
            "https://www.alphavantage.co/query",
            params=params,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()
        feed = data.get("feed", [])

        if not feed:
            return {
                "sentiment": "UNKNOWN",
                "score": 0,
                "headlines": []
            }

        scores = []
        headlines = []

        for article in feed[:10]:
            try:
                score = float(
                    article.get(
                        "overall_sentiment_score",
                        0
                    )
                )
            except (TypeError, ValueError):
                score = 0

            scores.append(score)

            headlines.append({
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "score": round(score, 3)
            })

        if not scores:
            return {
                "sentiment": "UNKNOWN",
                "score": 0,
                "headlines": headlines[:5]
            }

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

    return "WAIT"


def update_asset(symbol, asset):
    try:
        price = get_price(symbol)

        asset["price"] = price
        asset["prices"].append(price)
        asset["error"] = ""

        news = get_news_sentiment(
            symbol,
            asset["type"]
        )

        asset["news_sentiment"] = news.get(
            "sentiment",
            "UNKNOWN"
        )

        asset["news_score"] = news.get(
            "score",
            0
        )

        asset["headlines"] = news.get(
            "headlines",
            []
        )

        new_signal = calculate_signal(asset)

        if (
            new_signal in ("BUY", "SELL")
            and new_signal != asset["signal"]
        ):
            signals.insert(
                0,
                {
                    "time": datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "symbol": symbol,
                    "signal": new_signal,
                    "price": price
                }
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
        "samples": len(asset["prices"])
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def status():
    if running:
        for symbol, asset in assets.items():
            update_asset(symbol, asset)

    return jsonify({
        "running": running,
        "assets": {
            symbol: serialize_asset(asset)
            for symbol, asset in assets.items()
        },
        "signals": signals[:20]
    })


@app.route("/api/add", methods=["POST"])
def add_asset():
    data = request.get_json(silent=True) or {}

    symbol = str(
        data.get("symbol", "")
    ).upper().strip()

    asset_type = str(
        data.get("type", "stock")
    ).lower().strip()

    if not symbol:
        return jsonify({
            "error": "Symbol required"
        }), 400

    if asset_type not in ("stock", "crypto"):
        asset_type = "stock"

    if asset_type == "crypto":
        symbol = symbol.replace("/", "-")

        if "-" not in symbol:
            symbol += "-USD"

    if symbol not in assets:
        assets[symbol] = {
            "type": asset_type,
            "price": 0,
            "prices": deque(maxlen=SLOW_WINDOW),
            "signal": "WAIT",
            "news_sentiment": "UNKNOWN",
            "news_score": 0,
            "headlines": [],
            "error": ""
        }

    return jsonify({
        "ok": True,
        "symbol": symbol
    })


@app.route("/api/remove", methods=["POST"])
def remove_asset():
    data = request.get_json(silent=True) or {}

    symbol = str(
        data.get("symbol", "")
    ).upper().strip()

    if symbol in assets:
        del assets[symbol]

    return jsonify({
        "ok": True
    })


@app.route("/api/start", methods=["POST"])
def start():
    global running

    running = True

    return jsonify({
        "running": running
    })


@app.route("/api/stop", methods=["POST"])
def stop():
    global running

    running = False

    return jsonify({
        "running": running
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok"
    })


if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
