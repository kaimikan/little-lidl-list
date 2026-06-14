"""Score Lidl products by how useful they are for a training-focused diet.

This is a deliberately transparent heuristic over the *product name* plus the
scraped *category* and *price*. It is not a nutrition database — it's a ranked
shortlist generator. The model, rewritten from the original additive-keyword
version, addresses four problems that version had:

  1. Substring matching mislabelled foods — ``"ориз"`` (rice) matched inside
     ``"чоризо"`` (chorizo). We now match on a **left word-boundary + stem**, so
     Bulgarian inflections still match (``ориз`` → ``оризови``) but a stem can't
     match mid-word.
  2. Additive stacking let the keyword-densest *name* win (a dessert bar scored
     higher than chicken). We now take the **best single role value**, not a sum,
     and cap bonuses — so naming tricks can't inflate a score.
  3. Sugar-free items were penalised for the word ``захар``. The ``без … захар``
     phrase now suppresses the sugar penalty and grants a small quality bonus.
  4. Over half the catalogue scored 0 because it relied on the name alone. The
     scraped **category** now seeds a role for otherwise-unmatched items (an
     unmatched item in *Прясно месо* is almost certainly protein) and gates out
     impossible roles (a "protein" bar in *Снаксове и сладки* isn't protein).

``score`` (the health score) stays on roughly the same 0–15 scale the rest of
the app and its thresholds expect. ``value`` (health per euro) is exposed as a
cheap price signal used as a tiebreaker — price never makes a food *unhealthy*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lidl.scraper import Product

# Roles the meal planner buckets on. Keep these names stable — mealplan.py and
# the web UI's tag filters depend on them.
ROLE_PROTEIN = "protein"
ROLE_CARBS = "carbs"
ROLE_VEG = "vegetable"
ROLE_FRUIT = "fruit"
ROLE_FAT = "healthy_fat"
ROLE_SUPP = "supplement"
HEALTHY_ROLES = {ROLE_PROTEIN, ROLE_CARBS, ROLE_VEG, ROLE_FRUIT, ROLE_FAT, ROLE_SUPP}


# ── Food table ───────────────────────────────────────────────────────
# (stems, role, value). Stems match on a left word-boundary so inflected
# forms are caught (пилешк → пилешко/пилешка). value is a rough "how good for
# training" weight; we take the BEST value per role rather than summing, so
# synonyms and cuts (филе, стек) can't double-count.

@dataclass(frozen=True)
class Food:
    stems: tuple[str, ...]
    role: str
    value: int
    exact: bool = False   # match the whole word only (for short, collidable stems)


FOODS: list[Food] = [
    # ── Protein ──────────────────────────────────────────────
    Food(("извара", "cottage", "творог"), ROLE_PROTEIN, 9),
    Food(("скир", "skyr"), ROLE_PROTEIN, 9),
    Food(("протеин",), ROLE_SUPP, 9),               # powder; bars get penalised below
    Food(("пилешк", "пиле", "chicken"), ROLE_PROTEIN, 8),
    Food(("пуешк", "пуйка", "turkey"), ROLE_PROTEIN, 8),
    Food(("яйц", "яйца", "eggs"), ROLE_PROTEIN, 8),
    Food(("риба", "рибн", "fish"), ROLE_PROTEIN, 8),
    Food(("сьомга", "salmon"), ROLE_PROTEIN, 8),
    Food(("пъстърв", "trout"), ROLE_PROTEIN, 8),
    Food(("скумри", "mackerel"), ROLE_PROTEIN, 7),
    Food(("тон", "tuna"), ROLE_PROTEIN, 8, exact=True),
    Food(("херинг", "сардин", "цаца", "хек", "треска", "ципур", "лаврак"), ROLE_PROTEIN, 7),
    Food(("телешк", "говежд", "beef", "veal"), ROLE_PROTEIN, 7),
    Food(("морск", "скариди", "калмар", "миди", "seafood", "shrimp"), ROLE_PROTEIN, 7),
    Food(("цедено", "гръцко кисело", "greek yog"), ROLE_PROTEIN, 8),
    Food(("кисело мляко", "yogurt", "йогурт"), ROLE_PROTEIN, 7),
    Food(("кефир", "айрян"), ROLE_PROTEIN, 5),
    Food(("кашкавал",), ROLE_PROTEIN, 6),
    Food(("сирене", "моцарел", "фета", "cheese", "халуми", "извара"), ROLE_PROTEIN, 6),
    Food(("кайма", "mince"), ROLE_PROTEIN, 5),
    Food(("свинск", "pork"), ROLE_PROTEIN, 5),
    Food(("прясно мляко", "fresh milk"), ROLE_PROTEIN, 5),
    Food(("шунка", "ham"), ROLE_PROTEIN, 4),
    Food(("тофу", "tofu", "едамаме", "edamame", "темпе"), ROLE_PROTEIN, 7),

    # ── Complex carbs ────────────────────────────────────────
    Food(("овес", "овесен", "oats", "oat"), ROLE_CARBS, 8),
    Food(("киноа", "quinoa"), ROLE_CARBS, 8),
    Food(("лещ", "lentil"), ROLE_CARBS, 8),
    Food(("елда", "buckwheat"), ROLE_CARBS, 7),
    Food(("булгур", "bulgur"), ROLE_CARBS, 7),
    Food(("нахут", "chickpea", "hummus", "хумус"), ROLE_CARBS, 7),
    Food(("боб", "фасул", "beans"), ROLE_CARBS, 7),
    Food(("грах", "peas"), ROLE_CARBS, 6),
    Food(("пълнозърнес", "цялозърнес", "wholegrain", "whole wheat"), ROLE_CARBS, 7),
    Food(("сладък картоф", "батат", "sweet potato"), ROLE_CARBS, 7),
    Food(("кафяв ориз", "brown rice"), ROLE_CARBS, 7),
    Food(("ориз", "rice"), ROLE_CARBS, 6),
    Food(("картоф", "potato"), ROLE_CARBS, 5),
    Food(("кускус", "couscous"), ROLE_CARBS, 6),
    Food(("спагети", "паста", "макарон", "pasta", "нудли", "noodle"), ROLE_CARBS, 4),

    # ── Vegetables (greens & veg only — NOT prepared "салата" dishes) ─
    Food(("спанак", "spinach"), ROLE_VEG, 8),
    Food(("броколи", "broccoli"), ROLE_VEG, 8),
    Food(("кейл", "къдраво зеле", "kale"), ROLE_VEG, 8),
    Food(("рукол", "аругула", "arugula", "rocket"), ROLE_VEG, 7),
    Food(("карфиол", "cauliflower"), ROLE_VEG, 7),
    Food(("аспержи", "asparagus"), ROLE_VEG, 7),
    Food(("марул", "айсберг", "ендивия", "lettuce"), ROLE_VEG, 5),
    Food(("домат", "tomato"), ROLE_VEG, 6),
    Food(("морков", "carrot"), ROLE_VEG, 6),
    Food(("тиквичк", "zucchini", "courgette"), ROLE_VEG, 6),
    Food(("патладжан", "eggplant", "aubergine"), ROLE_VEG, 6),
    Food(("гъб", "mushroom"), ROLE_VEG, 6),
    Food(("цвекло", "beet"), ROLE_VEG, 6),
    Food(("зелен фасул", "зелен боб", "green bean"), ROLE_VEG, 6),
    Food(("чушк", "пипер", "чушл", "pepper"), ROLE_VEG, 5),
    Food(("краставиц", "cucumber"), ROLE_VEG, 5),
    Food(("зеле", "cabbage"), ROLE_VEG, 5),
    Food(("целин", "celery"), ROLE_VEG, 5),
    Food(("царевиц", "corn"), ROLE_VEG, 5),
    Food(("тиква", "pumpkin", "squash"), ROLE_VEG, 5),
    Food(("репичк", "radish"), ROLE_VEG, 5),
    Food(("праз", "leek"), ROLE_VEG, 4),
    Food(("чесън", "garlic"), ROLE_VEG, 4),
    Food(("лук", "onion"), ROLE_VEG, 4, exact=True),

    # ── Fruit ────────────────────────────────────────────────
    Food(("боровинк", "blueberry"), ROLE_FRUIT, 7),
    Food(("малин", "raspberry"), ROLE_FRUIT, 7),
    Food(("ягод", "strawberry"), ROLE_FRUIT, 7),
    Food(("къпин", "blackberry"), ROLE_FRUIT, 7),
    Food(("киви", "kiwi"), ROLE_FRUIT, 7),
    Food(("нар", "pomegranate"), ROLE_FRUIT, 7, exact=True),
    Food(("банан", "banana"), ROLE_FRUIT, 7),
    Food(("ябълк", "apple"), ROLE_FRUIT, 6),
    Food(("портокал", "мандарин", "orange", "грейпфрут"), ROLE_FRUIT, 6),
    Food(("круш", "pear"), ROLE_FRUIT, 6),
    Food(("праскова", "кайси", "peach", "apricot", "нектарин"), ROLE_FRUIT, 6),
    Food(("смокин", "fig"), ROLE_FRUIT, 6),
    Food(("манго", "mango", "ананас", "pineapple"), ROLE_FRUIT, 6),
    Food(("череш", "cherry", "вишн"), ROLE_FRUIT, 6),
    Food(("грозде", "grape"), ROLE_FRUIT, 5),
    Food(("диня", "пъпеш", "watermelon", "melon"), ROLE_FRUIT, 5),

    # ── Healthy fats ─────────────────────────────────────────
    Food(("авокадо", "avocado"), ROLE_FAT, 8),
    Food(("чиа", "chia"), ROLE_FAT, 8),
    Food(("зехтин", "маслинов", "olive oil"), ROLE_FAT, 8),
    Food(("бадем", "almond"), ROLE_FAT, 7),
    Food(("орех", "walnut"), ROLE_FAT, 7),
    Food(("лешник", "hazelnut"), ROLE_FAT, 7),
    Food(("тахан", "tahini"), ROLE_FAT, 7),
    Food(("фъстъчено масло", "peanut butter"), ROLE_FAT, 7),
    Food(("кашу", "cashew"), ROLE_FAT, 6),
    Food(("ленен", "ленено", "flax"), ROLE_FAT, 6),
    Food(("семк", "семен", "семе", "seeds"), ROLE_FAT, 6),
    Food(("маслин", "olive"), ROLE_FAT, 5),
]

# ── Quality modifiers (small, capped bonus) ──────────────────────────
QUALITY: list[Food] = [
    Food(("био", "organic", "bio"), "quality", 2, exact=True),
    Food(("без захар", "без добавена захар", "sugar free", "sugar-free", "no added sugar"),
         "quality", 2),
]
QUALITY_CAP = 3

# Phrases that mean "this product is sugar-free" — they must suppress the
# generic ``захар`` penalty (otherwise sugar-free items get penalised).
SUGAR_FREE = ("без захар", "без добавена захар", "без захари",
              "sugar free", "sugar-free", "no added sugar")


# ── Penalties ────────────────────────────────────────────────────────
# (stems, penalty, tag). Penalties are subtracted from health; a strong
# penalty also strips healthy role tags so the planner won't pick the item.
@dataclass(frozen=True)
class Penalty:
    stems: tuple[str, ...]
    cost: int
    tag: str
    exact: bool = False


PENALTIES: list[Penalty] = [
    Penalty(("чипс", "chips"), 7, "junk"),
    Penalty(("бонбон", "candy", "близалк"), 7, "junk"),
    Penalty(("бисквит", "cookie", "крекер", "cracker"), 6, "junk"),
    Penalty(("шоколад", "chocolate", "нутела", "nutella"), 5, "junk"),
    Penalty(("вафл", "wafer", "waffle"), 5, "junk"),
    Penalty(("торт", "cake", "кекс", "мъфин", "muffin", "козунак"), 6, "junk"),
    Penalty(("сладолед", "ice cream"), 5, "junk"),
    Penalty(("кроасан", "croissant", "понич", "donut", "донат"), 5, "junk"),
    Penalty(("десерт", "dessert"), 5, "junk"),
    Penalty(("блокче", "bar"), 5, "junk"),       # "протеин блокче" → candy, not protein
    Penalty(("бар",), 4, "junk", exact=True),
    Penalty(("пудинг", "pudding", "желе", "jelly", "крем"), 4, "junk", exact=False),
    Penalty(("пуканк", "popcorn", "солет", "снакс", "snack"), 4, "junk"),
    Penalty(("сироп", "syrup", "конфитюр", "мармалад", "jam", "marmalade"), 4, "junk"),
    Penalty(("нектар", "nectar"), 4, "junk"),
    Penalty(("мед", "honey"), 3, "junk", exact=True),
    Penalty(("пица", "pizza", "тесто", "тестен", "кифл", "pastry"), 4, "junk"),
    Penalty(("захар", "sugar"), 3, "junk"),       # suppressed by SUGAR_FREE
    # Sugary / empty-calorie drinks
    Penalty(("газиран", "carbonated", "кола", "cola", "fanta", "фанта", "спрайт"), 6, "junk"),
    Penalty(("лимонад", "lemonade", "енергийн", "energy drink"), 5, "junk"),
    Penalty(("сок", "juice"), 3, "junk"),
    # Alcohol
    Penalty(("бира", "beer", "ейл", "lager"), 4, "alcohol"),
    Penalty(("вино", "wine", "просеко", "шампан"), 4, "alcohol", exact=False),
    Penalty(("водка", "уиск", "whisky", "whiskey", "ракия", "джин", "ликьор", "текила"),
            6, "alcohol"),
    Penalty(("ром", "rum"), 6, "alcohol", exact=True),
    # Processed meat & condiments
    Penalty(("салам", "надениц", "кренвирш", "колбас", "луканк", "суджук",
             "пастърм", "бекон", "salami", "sausage", "bacon"), 4, "processed"),
    Penalty(("нъгетс", "nugget", "паниран", "breaded", "хот-дог", "hot dog"), 5, "processed"),
    Penalty(("майонез", "mayonnaise", "кетчуп", "ketchup", "маргарин", "margarine"),
            4, "processed"),
    # Prepared deli items: ready "салата" is usually mayo-dressed, "дип"/"крокет"/
    # "пане" are fried/processed. A light nudge so they fall below plain cuts.
    Penalty(("дип", "крокет", "пържен", "fried", "панипане", "пане"), 3, "processed"),
    Penalty(("салата",), 2, "processed"),
]

# Bread / baked goods — refined carbs. They often contain incidental "good"
# words (focaccia *with olive oil*); detecting bread forces a carbs role and
# strips an incidental healthy-fat tag so bread can't fill a "healthy fat" slot.
BREAD_STEMS = ("хляб", "питк", "питa", "багет", "багета", "фокач", "тост", "лаваш",
               "тортил", "кифл", "симид", "франзел", "брускет", "панини")


# ── Category priors ──────────────────────────────────────────────────
# base: (role, value) seeded ONLY for items that matched no food at all — this
#       is the recall fallback that rescues the ~57% name-only blind spot.
# penalty: flat health penalty for the whole category.
# block: strip healthy roles & mark junk (sweets/snacks can't be real food).
@dataclass(frozen=True)
class CategoryPrior:
    base: tuple[str, int] | None = None
    penalty: int = 0
    block: bool = False


CATEGORY_PRIORS: dict[str, CategoryPrior] = {
    "Прясно месо": CategoryPrior(base=(ROLE_PROTEIN, 6)),
    "Риба и морски дарове": CategoryPrior(base=(ROLE_PROTEIN, 6)),
    "Плодове и зеленчуци": CategoryPrior(base=(ROLE_VEG, 4)),
    "Снаксове и сладки": CategoryPrior(penalty=4, block=True),
    "Деликатеси": CategoryPrior(penalty=2),
    "Напитки": CategoryPrior(penalty=2),
}


# ── Compiled matchers ────────────────────────────────────────────────
def _compile(stem: str, exact: bool) -> re.Pattern:
    """Left word-boundary match. exact=True also anchors the right side.

    ``\\b`` is Unicode-aware for str patterns, so it works on Cyrillic. A bare
    left boundary lets inflected suffixes through (``ориз`` matches ``оризови``)
    while preventing mid-word matches (``ориз`` will NOT match ``чоризо``).
    """
    esc = re.escape(stem.lower())
    return re.compile(rf"\b{esc}\b" if exact else rf"\b{esc}")


_FOOD_MATCHERS = [(f, [_compile(s, f.exact) for s in f.stems]) for f in FOODS]
_QUALITY_MATCHERS = [(q, [_compile(s, q.exact) for s in q.stems]) for q in QUALITY]
_PENALTY_MATCHERS = [(p, [_compile(s, p.exact) for s in p.stems]) for p in PENALTIES]
_BREAD_MATCHERS = [_compile(s, False) for s in BREAD_STEMS]


def _hit(matchers: list[re.Pattern], name: str) -> bool:
    return any(m.search(name) for m in matchers)


@dataclass
class ScoredProduct:
    product: Product
    score: int                       # final health score (0–15-ish); back-compat name
    tags: list[str]
    reason: str
    health: int = 0                  # alias of score, kept explicit for clarity
    value: float = 0.0               # health per euro — price tiebreaker
    roles: dict[str, int] = field(default_factory=dict)


def _price_eur(product: Product) -> float | None:
    m = re.search(r"(\d+[.,]\d{2})", product.price or "")
    return float(m.group(1).replace(",", ".")) if m else None


def score_product(product: Product) -> ScoredProduct:
    name = product.name.lower().strip()
    category = product.category or ""
    prior = CATEGORY_PRIORS.get(category, CategoryPrior())
    reasons: list[str] = []

    # 1) Best value per role from name matches (max, not sum).
    roles: dict[str, int] = {}
    for food, matchers in _FOOD_MATCHERS:
        if _hit(matchers, name):
            if food.value > roles.get(food.role, 0):
                roles[food.role] = food.value

    # 2) Bread override — force carbs, drop an incidental healthy-fat tag.
    if _hit(_BREAD_MATCHERS, name):
        roles[ROLE_CARBS] = max(roles.get(ROLE_CARBS, 0), 4)
        roles.pop(ROLE_FAT, None)
        reasons.append("bread→carbs")

    # 3) Recall fallback: nothing matched but the category implies a role.
    if not roles and prior.base and not prior.block:
        role, val = prior.base
        roles[role] = val
        reasons.append(f"cat:{category}→{role}")

    # 4) Quality bonus (capped).
    quality_bonus = 0
    quality_tags: list[str] = []
    for q, matchers in _QUALITY_MATCHERS:
        if _hit(matchers, name):
            quality_bonus += q.value
            if q.stems[0] not in quality_tags:
                quality_tags.append("quality")
            reasons.append(f"+{q.value} quality:{q.stems[0]}")
    quality_bonus = min(quality_bonus, QUALITY_CAP)

    # 5) Penalties (with the sugar-free guard).
    sugar_free = any(p in name for p in SUGAR_FREE)
    penalty = 0
    penalty_tags: list[str] = []
    for p, matchers in _PENALTY_MATCHERS:
        if p.tag == "junk" and p.stems[0] in ("захар", "sugar") and sugar_free:
            continue  # don't penalise a product for *not* containing sugar
        if _hit(matchers, name):
            penalty += p.cost
            if p.tag not in penalty_tags:
                penalty_tags.append(p.tag)
            reasons.append(f"-{p.cost} {p.tag}:{p.stems[0]}")

    # 6) Compose health: best role + secondary-variety bonus + quality − penalty.
    if roles:
        best_role = max(roles, key=lambda r: roles[r])
        best = roles[best_role]
        secondary = min(sum(1 for r in roles if r != best_role and r in HEALTHY_ROLES), 2)
        for r, v in sorted(roles.items(), key=lambda kv: -kv[1]):
            reasons.append(f"+{v} {r}")
    else:
        best = secondary = 0

    health = best + secondary + quality_bonus - penalty + prior.penalty * -1
    if prior.penalty:
        reasons.append(f"-{prior.penalty} cat:{category}")

    # 7) Category block (sweets/snacks): can't be real food.
    blocked = prior.block
    if blocked:
        roles = {}
        health = min(health, 0)
        if "junk" not in penalty_tags:
            penalty_tags.append("junk")
        reasons.append(f"blocked:{category}")

    # 8) Strip healthy role tags when the item is really junk (net too low).
    keep_roles = health >= 4 and not blocked

    health = max(-5, min(15, health))

    tags: list[str] = []
    if keep_roles:
        for r, _ in sorted(roles.items(), key=lambda kv: -kv[1]):
            tags.append(r)
    tags += [t for t in quality_tags if t not in tags]
    tags += [t for t in penalty_tags if t not in tags]

    price = _price_eur(product)
    value = round(health / price, 2) if price and health > 0 else 0.0

    return ScoredProduct(
        product=product,
        score=health,
        tags=tags,
        reason=", ".join(reasons) if reasons else "no match",
        health=health,
        value=value,
        roles=roles if keep_roles else {},
    )


def rank_products(products: list[Product], min_score: int = 1) -> list[ScoredProduct]:
    """Score and rank products, returning only those scoring >= min_score.

    Ties on health are broken by ``value`` (more health per euro first), so the
    meal planner and digest prefer the better-value item among equals.
    """
    scored = [score_product(p) for p in products]
    good = [s for s in scored if s.score >= min_score]
    good.sort(key=lambda s: (s.score, s.value), reverse=True)
    return good
