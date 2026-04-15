# Little Lidl List

Scan Lidl Bulgaria's weekly offers and find the best items for a training-focused diet. Automatically scrapes [lidl.bg](https://www.lidl.bg), scores products by nutritional value, and displays results in a visual web interface.

![Screenshot](screenshot.png)

## Features

- **Scrapes 200+ products** across 16 food categories from Lidl Bulgaria
- **Health/fitness scoring** — ranks items by relevance for training (high protein, complex carbs, healthy fats, vegetables)
- **Product images** embedded directly in the UI
- **Sale filter** — toggle to show only discounted items
- **Category & tag filters** — filter by food category or nutritional tag (protein, carbs, healthy fat, vegetable, fruit, supplement)
- **Light/dark theme** — Lidl-branded color scheme with toggle
- **Caching** — scrape once, browse instantly with cached results
- **CLI** — terminal interface with Rich tables

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate    # Windows
# source .venv/bin/activate  # Linux/macOS

pip install -e .
playwright install chromium
```

## Usage

### Quick Start (Windows)

Double-click **`start.bat`** — it handles setup on first run and launches the web UI.

### Web UI

```bash
python -m lidl.app
```

Opens the browser at `http://localhost:5000`.

### CLI

```bash
# Full scan (scrapes live, ~2 min)
lidl

# Use cached results
lidl --cache

# Top 20 picks with score >= 8
lidl --cache --top 20 --min-score 8

# Show the browser while scraping
lidl --no-headless

# List available categories
lidl --list-categories
```

## Scoring

Products are scored by keyword matching tuned for a training diet:

| Tag | Examples | Score boost |
|-----|----------|-------------|
| Protein | Chicken, salmon, eggs, cottage cheese, skyr, Greek yogurt | +7 to +9 |
| Complex carbs | Oats, rice, lentils, quinoa, sweet potato | +6 to +8 |
| Healthy fats | Olive oil, avocado, nuts, peanut butter | +6 to +8 |
| Vegetables | Broccoli, spinach, peppers, tomatoes | +5 to +8 |
| Fruit | Bananas, apples | +6 to +7 |

Junk food, alcohol, and heavily processed items receive negative scores.

## Tech Stack

- **Playwright** — headless Chromium for scraping the JS-rendered Lidl site
- **Flask** — lightweight web server and API
- **Rich** — terminal UI for the CLI
- **Vanilla JS/CSS** — no frontend framework needed
