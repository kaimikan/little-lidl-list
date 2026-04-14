"""Flask web app for Little Lidl List."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from flask import Flask, render_template, jsonify, request

from lidl.scraper import scrape, clean_price, parse_prices, FOOD_CATEGORIES, CACHE_FILE
from lidl.scorer import rank_products, score_product

app = Flask(__name__)

# Track scraping state
_scrape_lock = threading.Lock()
_scrape_status = {"running": False, "message": ""}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/products")
def api_products():
    """Return scored products as JSON."""
    min_score = int(request.args.get("min_score", 1))
    category = request.args.get("category", "")

    # Load from cache
    if not CACHE_FILE.exists():
        return jsonify({"products": [], "total": 0, "message": "No data yet. Click Scan to fetch products."})

    data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    from lidl.scraper import Product
    products = [Product(**p) for p in data]

    if category:
        products = [p for p in products if p.category == category]

    ranked = rank_products(products, min_score=min_score)

    results = []
    for sp in ranked:
        current, old = parse_prices(sp.product.price, sp.product.old_price)
        results.append({
            "name": sp.product.name,
            "price": current,
            "old_price": old,
            "category": sp.product.category,
            "url": sp.product.url,
            "score": sp.score,
            "tags": sp.tags,
            "reason": sp.reason,
        })

    return jsonify({
        "products": results,
        "total": len(data),
        "filtered": len(results),
    })


@app.route("/api/categories")
def api_categories():
    return jsonify(list(FOOD_CATEGORIES.keys()))


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """Trigger a fresh scrape in the background."""
    if _scrape_status["running"]:
        return jsonify({"status": "already_running", "message": "Scan already in progress..."})

    def do_scrape():
        _scrape_status["running"] = True
        _scrape_status["message"] = "Scraping Lidl Bulgaria..."
        try:
            scrape(headless=True, use_cache=False)
            _scrape_status["message"] = "Done!"
        except Exception as e:
            _scrape_status["message"] = f"Error: {e}"
        finally:
            _scrape_status["running"] = False

    thread = threading.Thread(target=do_scrape, daemon=True)
    thread.start()
    return jsonify({"status": "started", "message": "Scanning Lidl Bulgaria..."})


@app.route("/api/scan/status")
def api_scan_status():
    return jsonify({
        "running": _scrape_status["running"],
        "message": _scrape_status["message"],
    })


def main():
    import webbrowser
    webbrowser.open("http://localhost:5000")
    app.run(debug=False, port=5000)


if __name__ == "__main__":
    main()
