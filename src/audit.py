#!/usr/bin/env python3
"""Data-quality audit for data/models.json.

Complementary to validate.py: validate.py checks SHAPE (schema, enums, numeric
ranges). This checks CONTENT — duplicates, dead rows, missing provenance, and
the spread of the whole set. Run it after every collection.

Exit code 1 on errors (things that must not ship); warnings are informational.

    python src/audit.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "models.json"


def norm_name(value: str) -> str:
    """Normalize for comparison WITHOUT destroying meaningful symbols.

    '+' distinguishes 'Command A+' from 'Command A', so only case and
    whitespace are folded here — stripping punctuation would manufacture
    phantom duplicates.
    """
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def main() -> int:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    models = payload.get("models", [])
    errors: list[str] = []
    warnings: list[str] = []

    # 1. ids must be unique
    by_id: dict[str, list[dict]] = defaultdict(list)
    for m in models:
        by_id[m["id"]].append(m)
    for mid, group in by_id.items():
        if len(group) > 1:
            errors.append(f"duplicate id {mid!r} ({len(group)} records)")

    # 2. display names should be unique within a provider
    by_pn: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for m in models:
        by_pn[(m["provider"], norm_name(m["display_name"]))].append(m)
    for (provider, name), group in by_pn.items():
        if len(group) > 1:
            ids = ", ".join(g["id"] for g in group)
            errors.append(f"{provider}: two models share the name {name!r}: {ids}")

    # 3. cross-provider name reuse is legal but worth knowing about
    by_name: dict[str, set[str]] = defaultdict(set)
    for m in models:
        by_name[norm_name(m["display_name"])].add(m["provider"])
    cross = {n: p for n, p in by_name.items() if len(p) > 1}

    # 4. dead rows: no price AND no context is useless to a reader
    dead = [m["id"] for m in models
            if m["pricing"].get("input") is None and m["pricing"].get("output") is None
            and not m["context"].get("max_input_tokens")]

    # 5. provenance / as_of must always be present
    for m in models:
        if not m.get("provenance"):
            errors.append(f"{m['id']}: no provenance")
        if not m.get("as_of"):
            errors.append(f"{m['id']}: no as_of")

    conf = Counter(m.get("confidence") for m in models)
    sourced = Counter(p["source_type"] for m in models for p in m.get("provenance", []))
    priced = sum(1 for m in models if m["pricing"].get("input") is not None)
    with_ctx = sum(1 for m in models if m["context"].get("max_input_tokens"))

    print(f"models          {len(models)}")
    print(f"providers       {len({m['provider'] for m in models})}")
    print(f"priced          {priced} ({priced * 100 // max(len(models), 1)}%)")
    print(f"with context    {with_ctx} ({with_ctx * 100 // max(len(models), 1)}%)")
    print(f"confidence      {dict(conf)}")
    print(f"source types    {dict(sourced)}")
    print(f"cross-provider name reuse: {len(cross)}")

    for w in warnings:
        print(f"WARN  {w}")
    if dead:
        print(f"WARN  {len(dead)} record(s) with neither price nor context: {dead[:5]}")
    for e in errors:
        print(f"ERROR {e}")

    if errors:
        print(f"\nFAIL — {len(errors)} error(s)")
        return 1
    print("\nOK — no duplicates, all records sourced and dated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
