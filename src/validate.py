#!/usr/bin/env python3
"""Validate data/models.json against ModelWatch record rules.

Stdlib only. If the third-party `jsonschema` package is installed, it also
validates every record against data/schema.json for full schema coverage.

Exit code 0 = clean, 1 = problems found.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "models.json"
SCHEMA = ROOT / "data" / "schema.json"

REQUIRED = ["id", "provider", "display_name", "lifecycle", "context",
            "pricing", "as_of", "confidence", "provenance"]
STATUSES = {"preview", "beta", "ga", "deprecated", "retired", "unknown"}
CONFIDENCE = {"verified", "partly_verified", "unverified", "estimated"}
SOURCE_TYPES = {"vendor_docs", "vendor_api", "vendor_pricing_page", "third_party", "manual"}


def check_model(m: dict, errs: list[str]) -> None:
    mid = m.get("id", "<missing id>")
    for field in REQUIRED:
        if field not in m:
            errs.append(f"{mid}: missing required field '{field}'")

    if m.get("lifecycle", {}).get("status") not in STATUSES:
        errs.append(f"{mid}: bad lifecycle.status {m.get('lifecycle', {}).get('status')!r}")

    ctx = m.get("context", {})
    for key in ("max_input_tokens", "max_output_tokens"):
        value = ctx.get(key)
        if not (value is None or (isinstance(value, int) and value > 0)):
            errs.append(f"{mid}: context.{key} must be null or a positive int, got {value!r}")

    pricing = m.get("pricing", {})
    if pricing.get("unit") != "per_mtok":
        errs.append(f"{mid}: pricing.unit must be 'per_mtok'")
    for key in ("input", "output", "cached_input", "cache_write"):
        value = pricing.get(key)
        if not (value is None or (isinstance(value, (int, float)) and value >= 0)):
            errs.append(f"{mid}: pricing.{key} must be null or >= 0, got {value!r}")

    if m.get("confidence") not in CONFIDENCE:
        errs.append(f"{mid}: bad confidence {m.get('confidence')!r}")

    prov = m.get("provenance")
    if not isinstance(prov, list) or not prov:
        errs.append(f"{mid}: provenance must be a non-empty list")
    else:
        for entry in prov:
            for field in ("source_url", "source_type", "retrieved_at"):
                if not entry.get(field):
                    errs.append(f"{mid}: provenance entry missing '{field}'")
            if entry.get("source_type") not in SOURCE_TYPES:
                errs.append(f"{mid}: bad provenance source_type {entry.get('source_type')!r}")

    # Integrity rule: a price claimed as verified must state when it was true.
    if m.get("confidence") == "verified" and not m.get("as_of"):
        errs.append(f"{mid}: verified records must carry an as_of date")


def main() -> int:
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    errs: list[str] = []

    models = payload.get("models")
    if not isinstance(models, list) or not models:
        errs.append("top-level 'models' must be a non-empty list")
        models = []

    seen: set[str] = set()
    for model in models:
        check_model(model, errs)
        if model.get("id") in seen:
            errs.append(f"duplicate id {model.get('id')!r}")
        seen.add(model.get("id"))

    try:
        import jsonschema  # type: ignore
    except ImportError:
        pass
    else:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        for model in models:
            try:
                jsonschema.validate(model, schema)
            except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
                errs.append(f"{model.get('id')}: schema: {exc.message}")

    if errs:
        print(f"FAIL - {len(errs)} problem(s):")
        for err in errs:
            print("  -", err)
        return 1

    providers = {m["provider"] for m in models}
    print(f"OK - {len(models)} model(s) across {len(providers)} provider(s) validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
