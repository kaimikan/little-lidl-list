"""Flask web app for Little Lidl List."""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

from flask import Flask, render_template, jsonify, request, send_file, Response

from lidl.scraper import scrape, clean_price, parse_prices, FOOD_CATEGORIES, CACHE_FILE, Product
from lidl.scorer import rank_products, score_product
from lidl.mealplan import (
    build_meal_plan, shopping_list, build_checklist_text, export_image,
    select_items, MODES, OUT_DIR,
)

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
        # For old cached data, parse_prices handles the messy blob.
        # For new data, prices are already clean but parse_prices still works.
        current, old = parse_prices(sp.product.price, sp.product.old_price)
        results.append({
            "name": sp.product.name,
            "price": current,
            "old_price": old,
            "weight": sp.product.weight,
            "category": sp.product.category,
            "url": sp.product.url,
            "image_url": sp.product.image_url,
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


# ── Meal plan ────────────────────────────────────────────────────────

def _mealplan_from_cache(min_score: int, mode: str = "sale"):
    """Build a 3-meal plan from the cached scrape, or None if no cache.

    mode="sale" plans from on-sale picks; mode="best" from the highest-scoring
    items regardless of price.
    """
    if not CACHE_FILE.exists():
        return None
    data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    fields = Product.__dataclass_fields__
    products = [Product(**{k: v for k, v in d.items() if k in fields}) for d in data]
    ranked = rank_products(products, min_score=min_score)
    return build_meal_plan(select_items(ranked, mode))


def _mode_arg() -> str:
    return "best" if request.args.get("mode") == "best" else "sale"


@app.route("/api/mealplan")
def api_mealplan():
    """Return the 3-meal plan + shopping list as JSON, built from cache."""
    min_score = int(request.args.get("min_score", 5))
    mode = _mode_arg()
    meals = _mealplan_from_cache(min_score, mode)
    if meals is None:
        return jsonify({"meals": [], "shopping": [], "mode": mode,
                        "message": "No data yet. Click Scan Now to fetch products."})

    meals_json = [{
        "title": m.title,
        "emoji": m.emoji,
        "slots": [{
            "role": s.role,
            "name": s.item.product.name,
            "price": clean_price(s.item.product.price),
            "old_price": clean_price(s.item.product.old_price),
            "score": s.item.score,
            "category": s.item.product.category,
        } for s in m.slots],
    } for m in meals]

    shopping = [{
        "name": it.name, "price": it.price,
        "old_price": it.old_price, "category": it.category,
    } for it in shopping_list(meals)]

    msg = "" if meals_json else MODES[mode]["empty"]
    return jsonify({"meals": meals_json, "shopping": shopping,
                    "mode": mode, "message": msg})


@app.route("/api/mealplan/image")
def api_mealplan_image():
    """Render the branded meal-plan card to PNG and send it for download."""
    min_score = int(request.args.get("min_score", 5))
    mode = _mode_arg()
    meals = _mealplan_from_cache(min_score, mode)
    if not meals:
        return jsonify({"message": "No meal plan to render. Scan first."}), 404
    when = date.today().isoformat()
    slug = MODES[mode]["slug"]
    out = OUT_DIR / f"meal-plan{slug}-{when}.png"
    export_image(meals, when, out, subtitle=MODES[mode]["subtitle"])
    return send_file(out, mimetype="image/png", as_attachment=True,
                     download_name=f"lidl-meal-plan{slug}-{when}.png")


@app.route("/api/mealplan/checklist")
def api_mealplan_checklist():
    """Send the plain-text shopping checklist for download."""
    min_score = int(request.args.get("min_score", 5))
    mode = _mode_arg()
    meals = _mealplan_from_cache(min_score, mode)
    when = date.today().isoformat()
    slug = MODES[mode]["slug"]
    text = build_checklist_text(meals or [], when)
    return Response(text, mimetype="text/plain", headers={
        "Content-Disposition": f"attachment; filename=lidl-shopping{slug}-{when}.txt",
    })


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
