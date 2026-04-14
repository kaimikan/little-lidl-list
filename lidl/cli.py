"""CLI for little-lidl-list."""

from __future__ import annotations

import argparse
import io
import os
import sys

# Force UTF-8 output on Windows so Bulgarian text and symbols render correctly
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from lidl.scraper import scrape, clean_price, FOOD_CATEGORIES
from lidl.scorer import rank_products, ScoredProduct

console = Console(force_terminal=True)

TAG_COLORS = {
    "protein": "bold red",
    "carbs": "bold yellow",
    "fruit": "bold green",
    "vegetable": "bold green",
    "healthy_fat": "bold cyan",
    "supplement": "bold magenta",
    "quality": "bold blue",
    "junk": "dim red",
    "alcohol": "dim red",
    "processed": "dim red",
}


def _render_tags(tags: list[str]) -> Text:
    text = Text()
    for i, tag in enumerate(tags):
        if i > 0:
            text.append(" ")
        color = TAG_COLORS.get(tag, "white")
        text.append(f"[{tag}]", style=color)
    return text


def _render_score(score: int) -> Text:
    if score >= 12:
        return Text(f"{'★' * 5}  {score}", style="bold green")
    elif score >= 8:
        return Text(f"{'★' * 4}{'☆' * 1}  {score}", style="green")
    elif score >= 5:
        return Text(f"{'★' * 3}{'☆' * 2}  {score}", style="yellow")
    else:
        return Text(f"{'★' * 2}{'☆' * 3}  {score}", style="dim yellow")


def main():
    parser = argparse.ArgumentParser(
        prog="lidl",
        description="Scan Lidl Bulgaria offers for healthy items",
    )
    parser.add_argument(
        "--no-headless", action="store_true",
        help="Show the browser window while scraping",
    )
    parser.add_argument(
        "--cache", action="store_true",
        help="Use cached results instead of scraping fresh",
    )
    parser.add_argument(
        "--min-score", type=int, default=1,
        help="Minimum health score to display (default: 1)",
    )
    parser.add_argument(
        "--top", type=int, default=0,
        help="Show only top N results (0 = all)",
    )
    parser.add_argument(
        "--category", "-c", nargs="*",
        help="Scrape specific categories only",
    )
    parser.add_argument(
        "--list-categories", action="store_true",
        help="List available categories and exit",
    )
    args = parser.parse_args()

    if args.list_categories:
        console.print("\n[bold]Available categories:[/bold]\n")
        for name, path in FOOD_CATEGORIES.items():
            console.print(f"  • {name}")
        console.print()
        return

    console.print(
        Panel(
            "[bold]Little Lidl List[/bold] - Healthy picks for training",
            subtitle="Lidl Bulgaria",
            style="green",
        )
    )

    with console.status("[bold green]Scraping Lidl Bulgaria..."):
        products = scrape(
            categories=args.category,
            headless=not args.no_headless,
            use_cache=args.cache,
        )

    if not products:
        console.print("\n[yellow]No products found. The site structure may have changed.[/yellow]")
        console.print("Try running with [bold]--no-headless[/bold] to see what's happening.")
        sys.exit(1)

    console.print(f"\n[dim]Found {len(products)} products total. Scoring...[/dim]\n")

    ranked = rank_products(products, min_score=args.min_score)

    if args.top > 0:
        ranked = ranked[:args.top]

    if not ranked:
        console.print("[yellow]No products matched the health criteria.[/yellow]")
        sys.exit(0)

    table = Table(
        title=f"Top {len(ranked)} Healthy Picks",
        show_lines=True,
        title_style="bold green",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Product", style="bold", min_width=20, max_width=35, no_wrap=False)
    table.add_column("Price", justify="right", width=10)
    table.add_column("Score", width=12)
    table.add_column("Tags", width=14)
    table.add_column("Category", style="dim", width=16)

    for i, sp in enumerate(ranked, 1):
        price_display = clean_price(sp.product.price)
        old = clean_price(sp.product.old_price)
        if old:
            price_display += f" [dim strikethrough]({old})[/dim strikethrough]"

        table.add_row(
            str(i),
            sp.product.name,
            price_display,
            _render_score(sp.score),
            _render_tags(sp.tags),
            sp.product.category,
        )

    console.print(table)
    console.print(f"\n[dim]Tip: re-run with --cache to skip scraping next time[/dim]\n")


if __name__ == "__main__":
    main()
