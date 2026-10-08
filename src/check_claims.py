#!/usr/bin/env python3
"""Check the numbers rendered on the site against the data they claim to come from.

Deliberately does NOT import build_site. If the checker reused the generator's own
helpers, a wrong aggregation would be reproduced on both sides and match happily.
Everything here is recomputed from data/models.json with the simplest possible
logic, so the two are genuinely independent.

Born from a real incident: the report page rendered "363 of 372 records are backed
by first-party vendor documentation" when the truth was 9 — an inverted tuple
unpack that every other test happily passed.

    python src/check_claims.py
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DATA = ROOT / "data" / "models.json"

TILE = re.compile(r'<div class="k-label">([^<]*)</div><div class="k-value">([^<]*)</div>')


def money(value) -> str:
    return f"${value:,.2f}"


def tokens(value) -> str:
    return f"{value / 1_000_000:g}M" if value >= 1_000_000 else str(value)


def tiles(page: str) -> dict[str, str]:
    path = SITE / page
    if not path.exists():
        return {}
    return dict(TILE.findall(path.read_text(encoding="utf-8")))


def main() -> int:
    models = json.loads(DATA.read_text(encoding="utf-8"))["models"]
    failures: list[str] = []

    def expect(page: str, label: str, want: str) -> None:
        got = tiles(page).get(label)
        if got is None:
            failures.append(f"{page}: no tile labelled {label!r}")
        elif got != want:
            failures.append(f"{page}: {label!r} renders {got!r}, data says {want!r}")

    # --- index -------------------------------------------------------------
    prices = [m["pricing"]["input"] for m in models if m["pricing"].get("input") is not None]
    windows = [m["context"]["max_input_tokens"] for m in models if m["context"].get("max_input_tokens")]
    n_providers = len({m["provider"] for m in models})

    expect("index.html", "Models", f"{len(models):,}")
    expect("index.html", "Providers", f"{n_providers:,}")
    expect("index.html", "Cheapest input", money(min(prices)))
    expect("index.html", "Largest context", tokens(max(windows)))

    # --- report ------------------------------------------------------------
    expect("report.html", "Models", f"{len(models):,}")
    expect("report.html", "Providers", f"{n_providers:,}")
    expect("report.html", "Median input price", money(statistics.median(prices)))

    by_year: dict[str, list[int]] = {}
    for m in models:
        if m.get("released") and m["context"].get("max_input_tokens"):
            by_year.setdefault(m["released"][:4], []).append(m["context"]["max_input_tokens"])
    years = sorted(by_year)
    first = int(statistics.median(by_year[years[0]]))
    last = int(statistics.median(by_year[years[-1]]))
    expect("report.html", "Context growth", f"{last / first:.0f}×")

    # --- leaderboard -------------------------------------------------------
    scored = [m for m in models
              if isinstance(((m.get("benchmarks") or {}).get("artificial_analysis") or {})
                            .get("intelligence_index"), (int, float))]
    top = max(((m.get("benchmarks") or {}).get("artificial_analysis") or {})
              .get("intelligence_index") for m in scored)
    expect("leaderboard.html", "Ranked", f"{len(scored):,}")
    expect("leaderboard.html", "Top score", str(top))

    # --- trends ------------------------------------------------------------
    dated = sum(1 for m in models if m.get("released"))
    expect("trends.html", "Models", f"{len(models):,}")
    expect("trends.html", "With a release date", f"{dated:,}")

    # --- index integrity: the tile must not understate the table ------------
    table_rows = len(re.findall(r"<tr data-name=", (SITE / "index.html").read_text(encoding="utf-8")))
    if table_rows != len(models):
        failures.append(f"index.html: {table_rows} rows rendered for {len(models)} models")

    for f in failures:
        print(f"MISMATCH  {f}")
    if failures:
        print(f"\nFAIL — {len(failures)} rendered figure(s) disagree with the data")
        return 1
    print(f"OK — every checked figure on the site matches the data "
          f"({len(models)} models, {n_providers} providers).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
