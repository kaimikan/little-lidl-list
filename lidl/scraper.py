"""Scrape Lidl Bulgaria for current food offers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

BASE = "https://www.lidl.bg"

# Use /h/ subcategory URLs — /c/ category pages are hubs without product cards.
FOOD_CATEGORIES = {
    "Плодове и зеленчуци": "/h/plodove-i-zelenchutsi/h10071012",
    "Прясно месо": "/h/pryasno-meso/h10071016",
    "Риба и морски дарове": "/h/riba-i-morski-darove/h10071050",
    "Мляко и млечни продукти": "/h/mlyako-mlechni-produkti/h10071017",
    "Хляб и тестени изделия": "/h/khlyab-i-testeni-izdeliya/h10071015",
    "Основни храни": "/h/osnovni-khrani/h10071045",
    "Замразени продукти": "/h/zamrazeni-produkti/h10071049",
    "Охладени продукти": "/h/okhladeni-produkti/h10071020",
    "Деликатеси": "/h/delikatesi/h10071680",
    "Кафе и чай": "/h/kafe-i-chay/h10071683",
    "Консервирани храни": "/h/konservirani-khrani/h10071681",
    "Подправки и сосове": "/h/podpravki-i-sosove/h10071682",
    "Напитки": "/h/napitki/h10071022",
    "Снаксове и сладки": "/h/snaksove-i-sladki-izkusheniya/h10071044",
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
    """Parse price fields into (current_price, old_price).

    Handles two formats:
    - New (clean): price="1.89€*", old_price="4.29 € (8.39 ЛВ.)"
    - Old (blob):  price="6.99 € (13.67 ЛВ.)\\n-30%\\n4.89€*\\n..." old_price="6.99 € ..."
    """
    current = clean_price(raw_price)
    old = clean_price(raw_old)

    # If both are set and different, we're done (new clean format)
    if current and old and current != old:
        return current, old

    # If same or only one set, try the old blob format
    if raw_price and "\n" in raw_price:
        all_eur = re.findall(r"(\d+[.,]\d{2})\s*€", raw_price)
        if len(all_eur) >= 2:
            return all_eur[1] + " €", all_eur[0] + " €"

    # No old price
    return current, "" if current == old else old


def _accept_cookies(page) -> None:
    try:
        btn = page.locator("button:has-text('Приемам'), button:has-text('Accept')")
        if btn.count() > 0:
            btn.first.click(timeout=3000)
            page.wait_for_timeout(500)
    except Exception:
        pass


def _scroll_to_load_all(page) -> None:
    """Scroll down the page to trigger lazy-loading of product tiles."""
    prev_count = 0
    for step in range(20):
        page.evaluate(f"window.scrollTo(0, {(step + 1) * 800})")
        page.wait_for_timeout(600)
        count = page.locator(".product-grid-box").count()
        if count == prev_count and step > 2:
            break
        prev_count = count

    # Also click "load more" if present and not fully loaded
    for _ in range(10):
        try:
            counter = page.locator(".s-load-more")
            if counter.count() > 0:
                text = counter.first.inner_text()
                m = re.search(r"(\d+)\s*/\s*(\d+)", text)
                if m and m.group(1) == m.group(2):
                    break
            btn = page.locator("[class*='load-more'] button, button:has-text('Зареди още')")
            if btn.count() == 0 or not btn.first.is_visible():
                break
            btn.first.scroll_into_view_if_needed()
            btn.first.click(timeout=5000)
            page.wait_for_timeout(2000)
            # Scroll again after load more
            for s in range(5):
                page.evaluate(f"window.scrollTo(0, {(s + 1) * 800})")
                page.wait_for_timeout(600)
        except Exception:
            break

    # Scroll back to top
    page.evaluate("window.scrollTo(0, 0)")


def _extract_products(page) -> list[Product]:
    """Extract product cards from the currently loaded page."""
    _scroll_to_load_all(page)

    cards = page.locator(".product-grid-box")
    if cards.count() == 0:
        return []

    products: list[Product] = []

    for i in range(cards.count()):
        card = cards.nth(i)
        try:
            # Name — from the tile link
            name = ""
            name_el = card.locator(".odsc-tile__link")
            if name_el.count() > 0:
                name = name_el.first.inner_text().strip()

            if not name:
                continue

            # URL
            url = ""
            link = card.locator("a[href*='/p/']")
            if link.count() > 0:
                href = link.first.get_attribute("href") or ""
                url = href if href.startswith("http") else BASE + href

            # Old price — strikethrough element
            old_price = ""
            old_el = card.locator(".ods-price__stroke-price s")
            if old_el.count() > 0:
                old_price = old_el.first.inner_text().strip()

            # Current price — the .ods-price__value element (first one with €)
            price = ""
            val_els = card.locator(".ods-price__value")
            for j in range(val_els.count()):
                text = val_els.nth(j).inner_text().strip()
                if "€" in text:
                    price = text
                    break

            # If no EUR price found, take the first value
            if not price and val_els.count() > 0:
                price = val_els.first.inner_text().strip()

            # Weight / unit info from footer
            weight = ""
            footer = card.locator(".ods-price__footer")
            if footer.count() > 0:
                weight = footer.first.inner_text().strip()

            # Product image
            image_url = ""
            img_el = card.locator(".odsc-image-gallery__image")
            if img_el.count() > 0:
                image_url = img_el.first.get_attribute("src") or ""

            products.append(Product(
                name=name[:200],
                price=price,
                old_price=old_price,
                weight=weight,
                url=url,
                image_url=image_url,
            ))
        except Exception:
            continue

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
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
            except PwTimeout:
                continue

            _accept_cookies(page)
            page.wait_for_timeout(3000)

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
