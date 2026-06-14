"""Turn the on-sale healthy picks into a 3-meal plan, a shopping list, and
phone-friendly exports (a Lidl-branded image card + a plain-text checklist).

This chains onto the daily digest (``lidl.summary``): it consumes the same
``ScoredProduct`` items the scorer already produces, keeps the discounted ones,
and assembles breakfast / lunch / dinner around protein + complex carbs + veg.

    lidl-mealplan --cache        # plan from the last scrape (no fetching)
    lidl-mealplan                # scrape live, then plan
    lidl-mealplan --min-score 6  # raise the health bar for eligible items

Writes into ``summaries/``:
    meal-plan-<date>.md       the plan as Markdown
    meal-plan-<date>.png      a shareable image card (rendered via Playwright)
    shopping-list-<date>.txt  a plain-text checklist of the item names
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date
from html import escape
from pathlib import Path

from lidl.scraper import clean_price
from lidl.scorer import ScoredProduct, rank_products

BASE = Path(__file__).resolve().parent.parent
OUT_DIR = BASE / "summaries"

# Lidl brand palette (mirrors lidl/static/style.css — don't reinvent the look).
LIDL_BLUE = "#0050AA"
LIDL_YELLOW = "#FFF200"
LIDL_RED = "#E60A14"


@dataclass
class Slot:
    """One component of a meal, e.g. the protein or the carb."""
    role: str          # human label: "Protein", "Carb", "Veg"…
    item: ScoredProduct


@dataclass
class Meal:
    title: str         # "Breakfast"
    emoji: str
    slots: list[Slot] = field(default_factory=list)

    @property
    def dish(self) -> str:
        """A readable combo name, e.g. 'Пилешко филе + Ориз + Домати'."""
        return " + ".join(s.item.product.name for s in self.slots)


# Each meal asks for a sequence of (tag, role-label) slots. The planner fills
# them from the best-scoring item carrying that tag.
MEAL_TEMPLATES: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("Breakfast", "🌅", [("protein", "Protein"), ("carbs", "Carb"), ("fruit", "Fruit")]),
    ("Lunch", "☀️", [("protein", "Protein"), ("vegetable", "Veg"), ("carbs", "Carb")]),
    ("Dinner", "🌙", [("protein", "Protein"), ("vegetable", "Veg"), ("healthy_fat", "Healthy fat")]),
]

# Two plan flavours: what's worth buying *this week* vs. the ideal training
# basket regardless of price. The planner itself is price-agnostic — the caller
# picks the item pool via select_items().
MODES: dict[str, dict[str, str]] = {
    "sale": {
        "slug": "",
        "subtitle": "healthy picks on sale",
        "intro": "Three meals built from today's **discounted** healthy picks.",
        "empty": "No on-sale healthy picks to build a plan from right now.",
    },
    "best": {
        "slug": "-best",
        "subtitle": "healthiest picks",
        "intro": "Three meals built from the **highest-scoring** healthy picks, "
                 "on sale or not.",
        "empty": "No healthy picks to build a plan from yet — try a scan.",
    },
}


def is_on_sale(product) -> bool:
    """A product is discounted when it carries a struck-through old price."""
    return bool((product.old_price or "").strip())


def select_items(ranked: list[ScoredProduct], mode: str = "sale") -> list[ScoredProduct]:
    """Pick the item pool for a plan flavour: on-sale only, or everything."""
    if mode == "best":
        return list(ranked)
    return [sp for sp in ranked if is_on_sale(sp.product)]


def _buckets(items: list[ScoredProduct]) -> dict[str, list[ScoredProduct]]:
    """Group scored items by each tag they carry, best score first."""
    by_tag: dict[str, list[ScoredProduct]] = {}
    for sp in items:
        for tag in sp.tags:
            by_tag.setdefault(tag, []).append(sp)
    for tag in by_tag:
        by_tag[tag].sort(key=lambda s: s.score, reverse=True)
    return by_tag


def build_meal_plan(on_sale_items: list[ScoredProduct]) -> list[Meal]:
    """Assemble breakfast / lunch / dinner from the discounted healthy picks.

    Greedy: for each slot pick the highest-scoring item with the right tag that
    hasn't been used yet. If a tag is exhausted we allow a reuse rather than
    leave a hole; if it's entirely absent the slot is simply skipped.
    """
    by_tag = _buckets(on_sale_items)
    used: set[str] = set()
    meals: list[Meal] = []

    for title, emoji, slots in MEAL_TEMPLATES:
        meal = Meal(title=title, emoji=emoji)
        for tag, role in slots:
            pool = by_tag.get(tag, [])
            pick = next((s for s in pool if s.product.name not in used), None)
            if pick is None and pool:
                pick = pool[0]  # everything used — reuse the best rather than skip
            if pick is not None:
                used.add(pick.product.name)
                meal.slots.append(Slot(role=role, item=pick))
        if meal.slots:
            meals.append(meal)
    return meals


@dataclass
class ShoppingItem:
    name: str
    price: str
    old_price: str
    category: str


def shopping_list(meals: list[Meal]) -> list[ShoppingItem]:
    """Deduplicated list of the items the plan calls for, first-seen order."""
    seen: set[str] = set()
    out: list[ShoppingItem] = []
    for meal in meals:
        for slot in meal.slots:
            p = slot.item.product
            if p.name in seen:
                continue
            seen.add(p.name)
            out.append(ShoppingItem(
                name=p.name,
                price=clean_price(p.price),
                old_price=clean_price(p.old_price),
                category=p.category,
            ))
    return out


# ── Exports ─────────────────────────────────────────────────────────

def build_markdown(meals: list[Meal], when: str, mode: str = "sale") -> str:
    cfg = MODES.get(mode, MODES["sale"])
    lines = [f"# 🍽️ Lidl meal plan — {when}", ""]
    if not meals:
        lines.append(f"_{cfg['empty']}_")
        return "\n".join(lines)
    lines.append(cfg["intro"])
    lines.append("")
    for meal in meals:
        lines.append(f"## {meal.emoji} {meal.title}")
        lines.append("")
        for slot in meal.slots:
            p = slot.item.product
            now = clean_price(p.price)
            lines.append(f"- **{slot.role}:** {p.name} — {now} _(score {slot.item.score})_")
        lines.append("")
    lines.append("## 🛒 Shopping list")
    lines.append("")
    for it in shopping_list(meals):
        was = f" ~~{it.old_price}~~" if it.old_price else ""
        lines.append(f"- [ ] {it.name} — {it.price}{was}")
    lines += ["", "_Generated by little-lidl-list · prices from lidl.bg_"]
    return "\n".join(lines)


def build_checklist_text(meals: list[Meal], when: str) -> str:
    """Plain-text shopping checklist — copy/paste straight onto a phone."""
    lines = [f"Lidl shopping list — {when}", "=" * 32, ""]
    items = shopping_list(meals)
    if not items:
        lines.append("(nothing on sale cleared the bar today)")
        return "\n".join(lines) + "\n"
    for it in items:
        was = f"  (was {it.old_price})" if it.old_price else ""
        lines.append(f"[ ] {it.name} — {it.price}{was}")
    lines += ["", f"{len(items)} items · for {len(meals)} meals", "via little-lidl-list"]
    return "\n".join(lines) + "\n"


def build_card_html(meals: list[Meal], when: str,
                    subtitle: str = "healthy picks on sale") -> str:
    """A self-contained, phone-width HTML card in the Lidl palette.

    Rendered to PNG by ``export_image`` — kept inline (no template) so the
    export has no runtime dependency on Flask's template loader.
    """
    meal_blocks = []
    for meal in meals:
        rows = "".join(
            f'<div class="row">'
            f'<span class="role">{escape(slot.role)}</span>'
            f'<span class="item">{escape(slot.item.product.name)}</span>'
            f'<span class="price">{escape(clean_price(slot.item.product.price))}</span>'
            f"</div>"
            for slot in meal.slots
        )
        meal_blocks.append(
            f'<section class="meal">'
            f'<h2><span class="emoji">{meal.emoji}</span>{escape(meal.title)}</h2>'
            f"{rows}</section>"
        )

    shop = "".join(
        f'<li><span class="box"></span>{escape(it.name)}'
        f'<span class="sprice">{escape(it.price)}</span></li>'
        for it in shopping_list(meals)
    )

    return f"""<!doctype html><html lang="bg"><head><meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: Arial, "Helvetica Neue", sans-serif; background: #f0f2f5;
         width: 480px; color: #1a1d27; }}
  .card {{ width: 480px; background: #fff; }}
  header {{ background: {LIDL_BLUE}; color: #fff; padding: 22px 24px;
            display: flex; align-items: center; gap: 14px; }}
  .badge {{ width: 44px; height: 44px; border-radius: 9px; background: {LIDL_YELLOW};
            color: {LIDL_BLUE}; font-weight: 900; font-size: 30px; line-height: 44px;
            text-align: center; flex: 0 0 auto; }}
  header .t {{ font-size: 21px; font-weight: 800; }}
  header .d {{ font-size: 13px; opacity: .8; }}
  .meals {{ padding: 8px 24px 4px; }}
  .meal {{ padding: 16px 0; border-bottom: 1px solid #eef0f4; }}
  .meal:last-child {{ border-bottom: none; }}
  .meal h2 {{ font-size: 16px; color: {LIDL_BLUE}; margin-bottom: 10px;
              display: flex; align-items: center; gap: 8px; }}
  .emoji {{ font-size: 18px; }}
  .row {{ display: flex; align-items: baseline; gap: 10px; padding: 3px 0; }}
  .role {{ flex: 0 0 92px; font-size: 11px; text-transform: uppercase;
           letter-spacing: .04em; color: #6b7186; font-weight: 700; }}
  .item {{ flex: 1; font-size: 14px; }}
  .price {{ font-size: 14px; font-weight: 800; color: {LIDL_BLUE}; }}
  .shop {{ background: #f7f8fa; padding: 18px 24px 22px; }}
  .shop h3 {{ font-size: 14px; text-transform: uppercase; letter-spacing: .05em;
              color: #6b7186; margin-bottom: 12px; }}
  .shop ul {{ list-style: none; }}
  .shop li {{ display: flex; align-items: center; gap: 10px; padding: 5px 0;
              font-size: 14px; }}
  .box {{ width: 16px; height: 16px; border: 2px solid {LIDL_BLUE}; border-radius: 4px;
          flex: 0 0 auto; }}
  .sprice {{ margin-left: auto; font-weight: 700; color: {LIDL_BLUE}; }}
  footer {{ background: {LIDL_BLUE}; color: #fff; font-size: 11px; text-align: center;
            padding: 10px; opacity: .95; }}
  footer b {{ color: {LIDL_YELLOW}; }}
</style></head><body>
<div class="card">
  <header>
    <div class="badge">L</div>
    <div><div class="t">Meal plan</div><div class="d">{escape(when)} · {escape(subtitle)}</div></div>
  </header>
  <div class="meals">{''.join(meal_blocks) or '<p style="padding:24px">Nothing to plan today.</p>'}</div>
  <div class="shop"><h3>🛒 Shopping list</h3><ul>{shop}</ul></div>
  <footer>little-lidl-list · prices from <b>lidl.bg</b></footer>
</div></body></html>"""


def export_image(meals: list[Meal], when: str, out_path: Path,
                 subtitle: str = "healthy picks on sale") -> Path:
    """Screenshot the branded HTML card to a PNG using Playwright."""
    from playwright.sync_api import sync_playwright

    html = build_card_html(meals, when, subtitle=subtitle)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 480, "height": 800},
                                device_scale_factor=2)
        page.set_content(html, wait_until="networkidle")
        card = page.locator(".card")
        card.screenshot(path=str(out_path))
        browser.close()
    return out_path


def write_exports(meals: list[Meal], when: str, out_dir: Path,
                  make_image: bool = True, mode: str = "sale") -> dict[str, Path]:
    """Write the plan Markdown, checklist text, and (optionally) the PNG card."""
    cfg = MODES.get(mode, MODES["sale"])
    slug = cfg["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    md_file = out_dir / f"meal-plan{slug}-{when}.md"
    md_file.write_text(build_markdown(meals, when, mode=mode), encoding="utf-8")
    written["markdown"] = md_file

    txt_file = out_dir / f"shopping-list{slug}-{when}.txt"
    txt_file.write_text(build_checklist_text(meals, when), encoding="utf-8")
    written["checklist"] = txt_file

    if make_image:
        png_file = out_dir / f"meal-plan{slug}-{when}.png"
        try:
            export_image(meals, when, png_file, subtitle=cfg["subtitle"])
            written["image"] = png_file
        except Exception as e:  # don't let a render hiccup break the digest run
            print(f"[meal-plan image skipped: {e}]", file=sys.stderr)

    return written


def main():
    ap = argparse.ArgumentParser(
        prog="lidl-mealplan",
        description="Build a 3-meal plan + shopping list + phone exports from "
                    "the healthy Lidl picks")
    ap.add_argument("--mode", choices=["sale", "best", "both"], default="sale",
                    help="'sale' = on-sale picks (default), 'best' = healthiest "
                         "regardless of price, 'both' = write both plans")
    ap.add_argument("--min-score", type=int, default=5,
                    help="minimum health score for eligible items (default: 5)")
    ap.add_argument("--cache", action="store_true", help="use the cached scrape")
    ap.add_argument("--input", help="plan from an explicit products JSON file")
    ap.add_argument("--out", default=str(OUT_DIR), help="output directory")
    ap.add_argument("--no-image", action="store_true",
                    help="skip the PNG card (Markdown + checklist only)")
    ap.add_argument("--no-headless", action="store_true",
                    help="show the browser while scraping")
    args = ap.parse_args()

    # Reuse the digest's loader so behaviour matches the daily run exactly.
    from lidl.summary import load_products
    products = load_products(args.input, args.cache, headless=not args.no_headless)
    ranked = rank_products(products, min_score=args.min_score)

    when = date.today().isoformat()
    modes = ["sale", "best"] if args.mode == "both" else [args.mode]
    for mode in modes:
        meals = build_meal_plan(select_items(ranked, mode))
        written = write_exports(meals, when, Path(args.out),
                                make_image=not args.no_image, mode=mode)
        print(build_markdown(meals, when, mode=mode))
        print()
        for label, path in written.items():
            print(f"[{mode} {label}: {path}]", file=sys.stderr)


if __name__ == "__main__":
    main()
