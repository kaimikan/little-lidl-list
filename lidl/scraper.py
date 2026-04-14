"""Scrape Lidl Bulgaria for current food offers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

BASE = "https://www.lidl.bg"

FOOD_CATEGORIES = {
    "Плодове и зеленчуци": "/c/plodove-i-zelenchutsi/s10020754",
    "Прясно месо": "/h/pryasno-meso/h10071016",
    "Риба и морски дарове": "/h/riba-i-morski-darove/h10071050",
    "Мляко и млечни продукти": "/h/mlyako-mlechni-produkti/h10071017",
    "Хляб и тестени изделия": "/h/khlyab-i-testeni-izdeliya/h10071015",
    "Замразени продукти": "/h/zamrazeni-produkti/h10071049",
    "Кафе и чай": "/h/kafe-i-chay/h10071683",
    "Консервирани храни": "/h/konservirani-khrani/h10071681",
    "Акция": "/c/aktsiya/a10092267",
    "Трайно ниски цени": "/c/trayno-niski-tseni/a10085720",
}

CACHE_FILE = Path(__file__).parent.parent / ".cache" / "products.json"


@dataclass
class Product:
    name: str
    price: str = ""
    old_price: str = ""
    category: str = ""
    weight: str = ""
    url: str = ""
    image_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def clean_price(raw: str) -> str:
    """Extract the first EUR price from messy scraped text."""
    if not raw:
        return ""
    m = re.search(r"(\d+[.,]\d{2})\s*€", raw)
    if m:
        return m.group(1) + " €"
    m = re.search(r"(\d+[.,]\d{2})\s*[Лл][Вв]", raw)
    if m:
        return m.group(1) + " лв."
    m = re.search(r"(\d+[.,]\d{2})", raw)
    if m:
        return m.group(1)
    return raw.strip()[:20]


def parse_prices(raw_price: str, raw_old: str) -> tuple[str, str]:
    """Parse the raw price blob into (current_price, old_price).

    Lidl's scraped price field often looks like:
      '6.99 € (13.67 ЛВ.)\\n-30%\\n4.89€*\\n9.56ЛВ.*\\n200 g/опаковка'
    The first price is the original, and the one after АКЦИЯ / % / Lidl Plus
    is the actual discounted price.
    """
    if not raw_price:
        return clean_price(raw_old), ""

    # Find all EUR prices in the blob (e.g. "6.99 €", "4.89€*")
    all_eur = re.findall(r"(\d+[.,]\d{2})\s*€", raw_price)

    if len(all_eur) >= 2:
        # Has promo: first = old price, second = current price
        old = all_eur[0] + " €"
        current = all_eur[1] + " €"
        return current, old

    if len(all_eur) == 1:
        return all_eur[0] + " €", ""

    # Fallback to лв.
    all_lv = re.findall(r"(\d+[.,]\d{2})\s*[Лл][Вв]", raw_price)
    if len(all_lv) >= 2:
        return all_lv[1] + " лв.", all_lv[0] + " лв."
    if len(all_lv) == 1:
        return all_lv[0] + " лв.", ""

    return clean_price(raw_price), ""


def _accept_cookies(page) -> None:
    try:
        btn = page.locator("button:has-text('Приемам'), button:has-text('Accept')")
        if btn.count() > 0:
            btn.first.click(timeout=3000)
    except Exception:
        pass


def _extract_products(page) -> list[Product]:
    """Extract product cards from the currently loaded page."""
    products: list[Product] = []

    # Try to load all products by clicking "load more" repeatedly
    for _ in range(10):
        try:
            load_more = page.locator(
                "button:has-text('Зареди още'), "
                "button:has-text('Load more'), "
                "a:has-text('Зареди още')"
            )
            if load_more.count() > 0 and load_more.first.is_visible():
                load_more.first.click(timeout=5000)
                page.wait_for_timeout(1500)
            else:
                break
        except Exception:
            break

    # Extract from product grid items - Lidl uses various card selectors
    selectors = [
        "article[class*='product']",
        "[class*='ProductGrid'] [class*='product']",
        "[data-grid-box]",
        ".product-grid-box",
        "[class*='AProductGridBox']",
        ".ret-o-card",
        "[class*='OfferCard']",
        "[class*='ret-o-tile']",
    ]

    cards = None
    for sel in selectors:
        cards = page.locator(sel)
        if cards.count() > 0:
            break

    if not cards or cards.count() == 0:
        # Fallback: grab any element that looks like a product card
        cards = page.locator("[class*='grid'] a[href*='/p/']")
        if cards.count() == 0:
            # Last resort: look for price elements and work upwards
            return _extract_from_structured_data(page)

    for i in range(cards.count()):
        card = cards.nth(i)
        try:
            name = ""
            price = ""
            old_price = ""
            url = ""

            # Name
            for name_sel in [
                "[class*='product-title']", "[class*='ProductTitle']",
                "[class*='name']", "h3", "h2", "[class*='title']",
                "[class*='Title']",
            ]:
                el = card.locator(name_sel)
                if el.count() > 0:
                    name = el.first.inner_text().strip()
                    if name:
                        break

            if not name:
                name = card.inner_text().strip().split("\n")[0]

            # Price
            for price_sel in [
                "[class*='price']", "[class*='Price']",
                "[class*='pricebox']",
            ]:
                el = card.locator(price_sel)
                if el.count() > 0:
                    price_text = el.first.inner_text().strip()
                    if price_text:
                        price = price_text
                        break

            # Old price (strikethrough)
            for old_sel in [
                "[class*='strikethrough']", "[class*='oldprice']",
                "[class*='OldPrice']", "del", "s",
            ]:
                el = card.locator(old_sel)
                if el.count() > 0:
                    old_price = el.first.inner_text().strip()
                    break

            # URL
            link = card.locator("a[href]")
            if link.count() > 0:
                href = link.first.get_attribute("href") or ""
                url = href if href.startswith("http") else BASE + href

            if name and len(name) > 1:
                products.append(Product(
                    name=name[:200],
                    price=price,
                    old_price=old_price,
                    url=url,
                ))
        except Exception:
            continue

    return products


def _extract_from_structured_data(page) -> list[Product]:
    """Try to extract product data from JSON-LD or script tags."""
    products = []
    try:
        scripts = page.locator("script[type='application/ld+json']")
        for i in range(scripts.count()):
            data = json.loads(scripts.nth(i).inner_text())
            if isinstance(data, list):
                for item in data:
                    if item.get("@type") == "Product":
                        products.append(Product(
                            name=item.get("name", ""),
                            price=str(item.get("offers", {}).get("price", "")),
                            url=item.get("url", ""),
                        ))
            elif isinstance(data, dict) and data.get("@type") == "Product":
                products.append(Product(
                    name=data.get("name", ""),
                    price=str(data.get("offers", {}).get("price", "")),
                    url=data.get("url", ""),
                ))
    except Exception:
        pass
    return products


def scrape(
    categories: list[str] | None = None,
    headless: bool = True,
    use_cache: bool = False,
) -> list[Product]:
    """Scrape Lidl BG for food products.

    Args:
        categories: list of category keys to scrape (defaults to all).
        headless: run browser headlessly.
        use_cache: if True, return cached results when available.
    """
    if use_cache and CACHE_FILE.exists():
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return [Product(**p) for p in data]

    targets = categories or list(FOOD_CATEGORIES.keys())
    all_products: list[Product] = []
    seen_names: set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="bg-BG",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for cat_name in targets:
            path = FOOD_CATEGORIES.get(cat_name)
            if not path:
                continue

            url = BASE + path
            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
            except PwTimeout:
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                except Exception:
                    continue

            _accept_cookies(page)
            page.wait_for_timeout(2000)

            products = _extract_products(page)
            for p in products:
                p.category = cat_name
                key = p.name.lower().strip()
                if key not in seen_names:
                    seen_names.add(key)
                    all_products.append(p)

        browser.close()

    # Cache results
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps([p.to_dict() for p in all_products], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return all_products
