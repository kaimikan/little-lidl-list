"""Score products by how useful they are for a training man in his mid-20s."""

from __future__ import annotations

import re
from dataclasses import dataclass
from lidl.scraper import Product

# ── Keyword scoring tables ──────────────────────────────────────────
# Positive keywords → (score_boost, tag)
POSITIVE: list[tuple[list[str], int, str]] = [
    # High-protein staples
    (["пилешко", "пиле", "chicken"], 8, "protein"),
    (["телешко", "beef", "говеждо"], 7, "protein"),
    (["свинско", "pork"], 5, "protein"),
    (["риба", "сьомга", "скумрия", "пъстърва", "тон", "fish", "salmon", "tuna"], 8, "protein"),
    (["морски", "seafood", "скариди"], 7, "protein"),
    (["яйца", "eggs"], 8, "protein"),
    (["извара", "cottage", "творог"], 9, "protein"),
    (["кисело мляко", "yogurt", "йогурт"], 7, "protein"),
    (["сирене", "cheese", "фета"], 5, "protein"),
    (["шунка", "ham"], 4, "protein"),
    (["филе", "fillet"], 6, "protein"),
    (["стек", "steak"], 6, "protein"),
    (["кайма", "mince"], 5, "protein"),

    # Complex carbs
    (["ориз", "rice"], 6, "carbs"),
    (["овесени", "овес", "oats", "oat"], 8, "carbs"),
    (["пълнозърнест", "wholegrain", "цялозърнест"], 7, "carbs"),
    (["киноа", "quinoa"], 8, "carbs"),
    (["елда", "buckwheat"], 7, "carbs"),
    (["картоф", "potato"], 5, "carbs"),
    (["сладък картоф", "sweet potato", "батат"], 7, "carbs"),
    (["леща", "lentils"], 8, "carbs"),
    (["боб", "beans", "нахут", "chickpea"], 7, "carbs"),
    (["хляб пълнозърнест", "whole wheat bread"], 6, "carbs"),

    # Fruits & vegetables
    (["банан", "banana"], 7, "fruit"),
    (["ябълк", "apple"], 6, "fruit"),
    (["авокадо", "avocado"], 8, "healthy_fat"),
    (["спанак", "spinach"], 8, "vegetable"),
    (["броколи", "broccoli"], 8, "vegetable"),
    (["домат", "tomato"], 6, "vegetable"),
    (["краставиц", "cucumber"], 5, "vegetable"),
    (["морков", "carrot"], 6, "vegetable"),
    (["чушк", "pepper"], 5, "vegetable"),
    (["салат", "lettuce", "маруля"], 5, "vegetable"),
    (["зеле", "cabbage"], 5, "vegetable"),
    (["лук", "onion"], 4, "vegetable"),

    # Healthy fats
    (["зехтин", "olive oil", "маслиново"], 8, "healthy_fat"),
    (["бадем", "almond"], 7, "healthy_fat"),
    (["орех", "walnut", "nut"], 7, "healthy_fat"),
    (["фъстъчено масло", "peanut butter"], 7, "healthy_fat"),
    (["ленено", "flax"], 6, "healthy_fat"),

    # Supplements / fitness foods
    (["протеин", "protein"], 9, "supplement"),
    (["био", "organic", "bio"], 3, "quality"),
    (["без захар", "sugar free", "без добавена захар"], 4, "quality"),

    # Dairy good for training
    (["прясно мляко", "fresh milk"], 5, "protein"),
    (["скир", "skyr"], 9, "protein"),
]

# Negative keywords → (penalty, tag)
NEGATIVE: list[tuple[list[str], int, str]] = [
    (["бисквити", "cookies", "бисквит"], -6, "junk"),
    (["шоколад", "chocolate", "шоколадов"], -5, "junk"),
    (["чипс", "chips", "крекер"], -7, "junk"),
    (["бонбони", "candy", "бонбон"], -7, "junk"),
    (["кроасан", "croissant"], -5, "junk"),
    (["торт", "cake"], -6, "junk"),
    (["сладолед", "ice cream"], -5, "junk"),
    (["газирана", "carbonated", "кола", "cola", "фант"], -6, "junk"),
    (["бира", "beer"], -4, "alcohol"),
    (["вино", "wine"], -4, "alcohol"),
    (["водка", "vodка", "уиски", "whiskey"], -6, "alcohol"),
    (["майонеза", "mayonnaise", "кетчуп"], -4, "junk"),
    (["вафл", "wafer", "waffle"], -5, "junk"),
    (["сироп", "syrup"], -4, "junk"),
    (["захар", "sugar"], -3, "junk"),
    (["палачинк", "pancake mix"], -3, "junk"),
    (["наденица", "sausage", "салам", "кренвирш", "колбас"], -4, "processed"),
]


@dataclass
class ScoredProduct:
    product: Product
    score: int
    tags: list[str]
    reason: str


def _normalize(text: str) -> str:
    return text.lower().strip()


def score_product(product: Product) -> ScoredProduct:
    name = _normalize(product.name)
    total = 0
    tags: list[str] = []
    reasons: list[str] = []

    for keywords, boost, tag in POSITIVE:
        for kw in keywords:
            if kw.lower() in name:
                total += boost
                if tag not in tags:
                    tags.append(tag)
                reasons.append(f"+{boost} {kw}")
                break

    for keywords, penalty, tag in NEGATIVE:
        for kw in keywords:
            if kw.lower() in name:
                total += penalty
                if tag not in tags:
                    tags.append(tag)
                reasons.append(f"{penalty} {kw}")
                break

    return ScoredProduct(
        product=product,
        score=total,
        tags=tags,
        reason=", ".join(reasons) if reasons else "no match",
    )


def rank_products(
    products: list[Product],
    min_score: int = 1,
) -> list[ScoredProduct]:
    """Score and rank products, returning only those above min_score."""
    scored = [score_product(p) for p in products]
    good = [s for s in scored if s.score >= min_score]
    good.sort(key=lambda s: s.score, reverse=True)
    return good
