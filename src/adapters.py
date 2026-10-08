#!/usr/bin/env python3
"""Pure parsers and merge logic: raw provider payloads -> ModelWatch records.

No network, no filesystem - everything here is a pure function so it can be
unit-tested against fixtures (see ../tests/).
"""
from __future__ import annotations

from datetime import datetime, timezone

CONF_RANK = {"estimated": 0, "unverified": 1, "partly_verified": 2, "verified": 3}

# Sub-objects merged key-by-key (an incoming null means "unknown", never "erase").
NESTED = ("lifecycle", "context", "pricing", "capabilities")

PRICE_KEYS = ("input", "output", "cached_input", "cache_write")


def _priced(pricing: dict | None) -> bool:
    """True if this pricing object already states at least one real price."""
    return isinstance(pricing, dict) and any(pricing.get(k) is not None for k in PRICE_KEYS)


def _family(model_id: str) -> str | None:
    parts = model_id.split("-")
    if len(parts) >= 3 and parts[0] == "claude":
        return parts[1]
    return None


def _date_only(value: str | None) -> str | None:
    if not value:
        return None
    return value.split("T", 1)[0]


def modelwatch_records(payload: dict, *, retrieved_at: str) -> list[dict]:
    """Identity parser for an existing ModelWatch dataset (e.g. the seed file)."""
    return list(payload.get("models", []))


def anthropic_models_api(payload: dict, *, retrieved_at: str) -> list[dict]:
    """Parse an Anthropic `GET /v1/models` response into ModelWatch records.

    The Models API returns capability + limit facts but no pricing, so price
    fields are left null here and preserved from the seed during merge.
    """
    records = []
    for m in payload.get("data", []):
        caps = m.get("capabilities") or {}
        records.append({
            "id": m["id"],
            "provider": "anthropic",
            "display_name": m.get("display_name") or m["id"],
            "family": _family(m["id"]),
            "released": _date_only(m.get("created_at")),
            "lifecycle": {"status": "ga", "deprecated_at": None, "retired_at": None, "notice": None},
            "context": {
                "max_input_tokens": m.get("max_input_tokens"),
                "max_output_tokens": m.get("max_tokens"),
            },
            "pricing": {"currency": "USD", "unit": "per_mtok", "input": None,
                        "output": None, "cached_input": None, "cache_write": None, "notes": None},
            "capabilities": {
                "vision": caps.get("vision"),
                "tool_use": caps.get("tool_use"),
                "streaming": caps.get("streaming"),
                "structured_outputs": caps.get("structured_outputs"),
                "prompt_caching": caps.get("prompt_caching"),
                "batch": caps.get("batch"),
            },
            "as_of": _date_only(retrieved_at),
            "confidence": "verified",
            "provenance": [{
                "source_url": "https://api.anthropic.com/v1/models",
                "source_type": "vendor_api",
                "retrieved_at": _date_only(retrieved_at),
                "note": "Live Models API.",
            }],
        })
    return records


def _per_mtok(value) -> float | None:
    """OpenRouter quotes USD per *token* as strings; convert to per-million.

    It uses a negative sentinel (-1) for variable / not-applicable pricing
    (router pseudo-models). Negative values become None = unknown.
    """
    if value in (None, ""):
        return None
    try:
        per_mtok = float(value) * 1_000_000
    except (TypeError, ValueError):
        return None
    return round(per_mtok, 6) if per_mtok >= 0 else None


def _unix_date(value) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError, TypeError):
        return None


def _canonical_slug(model: str) -> str:
    """Normalize vendor version separators to the first-party id convention.

    OpenRouter writes `claude-opus-4.8`; the first-party id (and our seed) is
    `claude-opus-4-8`. Applied uniformly to every OpenRouter id, so it can only
    ever merge two names for the *same* model, never split one apart.
    """
    return model.replace(".", "-")


EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")


def _effort_order(efforts) -> list[str] | None:
    """Sort a provider's effort list into a canonical low->max order."""
    if not efforts:
        return None
    known = [e for e in EFFORT_ORDER if e in efforts]
    extra = sorted(e for e in efforts if e not in known)
    return known + extra


def _benchmarks(raw) -> dict | None:
    """Normalize the aggregator's benchmark block.

    Two shapes appear: `artificial_analysis` (a flat dict of named indices) and
    `design_arena` (a list of per-category ELO rows). Both are third-party
    scores, so they are carried as-is under their own key and never presented as
    first-party facts.
    """
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    aa = raw.get("artificial_analysis")
    if isinstance(aa, dict):
        indices = {k: v for k, v in aa.items() if isinstance(v, (int, float))}
        if indices:
            out["artificial_analysis"] = indices
    arena = raw.get("design_arena")
    if isinstance(arena, list):
        rows = [{k: it.get(k) for k in ("arena", "category", "elo", "win_rate", "rank")}
                for it in arena if isinstance(it, dict)]
        if rows:
            out["design_arena"] = rows
    return out or None


def _tiers(pricing: dict) -> list[dict] | None:
    """Higher-usage price bands (`overrides` in the source payload).

    Ignoring these was a silent correctness bug: ~62 models charge more above a
    prompt-size threshold, and we were rendering a single flat price for them —
    e.g. claude-haiku-5.5 is $0.10/MTok up to 100k tokens and **$0.50** beyond.
    The base pricing fields remain the FIRST band; each tier applies once the
    prompt exceeds `above_input_tokens`.
    """
    raw = pricing.get("overrides")
    if not isinstance(raw, list):
        return None
    out = []
    for o in raw:
        if not isinstance(o, dict) or not isinstance(o.get("min_prompt_tokens"), (int, float)):
            continue
        out.append({
            "above_input_tokens": int(o["min_prompt_tokens"]),
            "input": _per_mtok(o.get("prompt")),
            "output": _per_mtok(o.get("completion")),
            "cached_input": _per_mtok(o.get("input_cache_read")),
            "cache_write": _per_mtok(o.get("input_cache_write")),
        })
    out.sort(key=lambda t: t["above_input_tokens"])
    return out or None


def openrouter_models_api(payload: dict, *, retrieved_at: str) -> list[dict]:
    """Parse OpenRouter's public `GET /api/v1/models` catalog.

    A third-party aggregator: broad coverage (all vendors) but not first-party
    authority, so records are marked `partly_verified`. The confidence-aware
    merge means these can fill empty providers but never overwrite a
    first-party `verified` figure. `:batch` and other variant ids are skipped.
    """
    records = []
    for m in payload.get("data", []):
        mid = m.get("id", "")
        if not mid or ":" in mid:
            continue
        vendor, _, model = mid.partition("/")
        if not model:
            vendor, model = "unknown", mid
        vendor = vendor.lstrip("~")   # OpenRouter variant endpoints (~openai/...)
        if vendor == "openrouter":
            continue  # OpenRouter's own router pseudo-models, not vendor models

        arch = m.get("architecture") or {}
        inputs = arch.get("input_modalities") or []
        supported = set(m.get("supported_parameters") or [])
        pricing = m.get("pricing") or {}
        top = m.get("top_provider") or {}
        expires = _date_only(m.get("expiration_date"))

        # OpenRouter prefixes every name with the vendor ("Anthropic: Claude ...").
        # Strip that label - the provider column already carries it.
        name = m.get("name") or model
        if ": " in name:
            head, _, tail = name.partition(": ")
            if tail and len(head) <= 24:
                name = tail

        records.append({
            "id": _canonical_slug(model),
            "provider": vendor,
            "display_name": name,
            "family": None,
            "released": _unix_date(m.get("created")),
            "lifecycle": {
                "status": "retired" if (expires and expires < retrieved_at) else "ga",
                "deprecated_at": None,
                "retired_at": expires if (expires and expires < retrieved_at) else None,
                "notice": f"Listed expiry {expires}." if expires else None,
            },
            "context": {
                "max_input_tokens": m.get("context_length"),
                "max_output_tokens": top.get("max_completion_tokens"),
            },
            "pricing": {
                "currency": "USD", "unit": "per_mtok",
                "input": _per_mtok(pricing.get("prompt")),
                "output": _per_mtok(pricing.get("completion")),
                "cached_input": _per_mtok(pricing.get("input_cache_read")),
                "cache_write": _per_mtok(pricing.get("input_cache_write")),
                "tiers": _tiers(pricing),
                "notes": None,
            },
            # Only map what the payload actually states; everything else stays
            # absent (= unknown) rather than guessed.
            "capabilities": {
                "vision": ("image" in inputs) if inputs else None,
                "tool_use": ("tools" in supported) if supported else None,
                "structured_outputs": ("structured_outputs" in supported or "response_format" in supported) if supported else None,
                "sampling": ("temperature" in supported or "top_p" in supported) if supported else None,
                "modalities_in": arch.get("input_modalities") or None,
                "modalities_out": arch.get("output_modalities") or None,
                "effort_levels": _effort_order((m.get("reasoning") or {}).get("supported_efforts")),
            },
            "knowledge_cutoff": m.get("knowledge_cutoff"),
            # An exact repo id, not a guess: its presence is what "open weights" means here.
            "hugging_face_id": m.get("hugging_face_id"),
            "benchmarks": _benchmarks(m.get("benchmarks")),
            "as_of": _date_only(retrieved_at),
            "confidence": "partly_verified",
            "provenance": [{
                "source_url": "https://openrouter.ai/api/v1/models",
                "source_type": "third_party",
                "retrieved_at": _date_only(retrieved_at),
                "note": "OpenRouter public model catalog (aggregated; not first-party).",
            }],
        })
    return records


def merge_record(base: dict | None, incoming: dict) -> dict:
    """Confidence-aware field merge.

    Rules:
      * a `null` incoming value never erases a known fact;
      * an incoming value overrides an existing one only when the incoming
        source is at least as trustworthy (so a third-party aggregator cannot
        overwrite a first-party `verified` figure);
      * provenance lists are concatenated and de-duplicated;
      * `as_of` becomes the newest contributing date (last-confirmed semantics).
    """
    if base is None:
        return dict(incoming)

    rank_in = CONF_RANK.get(incoming.get("confidence"), -1)
    rank_base = CONF_RANK.get(base.get("confidence"), -1)
    trusted = rank_in >= rank_base

    out = dict(base)
    for key, value in incoming.items():
        if key in NESTED:
            base_obj = out.get(key) or {}
            incoming_obj = value or {}

            # A price object comes from EXACTLY ONE source. Never mix a
            # less-trusted source's price fields into an already-priced record;
            # instead, surface the disagreement so a human (or a later adapter)
            # can resolve it.
            if key == "pricing" and _priced(base_obj) and not trusted:
                disagreement = {
                    k: {"ours": base_obj.get(k), "theirs": incoming_obj.get(k)}
                    for k in PRICE_KEYS
                    if incoming_obj.get(k) is not None
                    and base_obj.get(k) is not None
                    and incoming_obj.get(k) != base_obj.get(k)
                }
                if disagreement:
                    source = (incoming.get("provenance") or [{}])[0].get("source_url")
                    out.setdefault("conflicts", []).append(
                        {"field": "pricing", "source_url": source, "disagreement": disagreement})
                continue

            merged = dict(base_obj)
            for sub_key, sub_value in incoming_obj.items():
                if sub_value is None:
                    continue
                if merged.get(sub_key) is None or trusted:
                    merged[sub_key] = sub_value
            out[key] = merged
        elif key == "provenance":
            combined = list(out.get("provenance") or []) + list(value or [])
            seen, deduped = set(), []
            for entry in combined:
                sig = (entry.get("source_url"), entry.get("retrieved_at"))
                if sig in seen:
                    continue
                seen.add(sig)
                deduped.append(entry)
            out["provenance"] = deduped
        elif key == "as_of":
            out["as_of"] = max(filter(None, [out.get("as_of"), value]))
        elif key == "confidence":
            if trusted:
                out["confidence"] = value
        elif value is not None:
            if out.get(key) is None or trusted:
                out[key] = value
    return out


# Registry of parsers, keyed by the `parser` field in data/sources.json.
# Defined last so every parser above is in scope.
PARSERS = {
    "modelwatch_records": modelwatch_records,
    "anthropic_models_api": anthropic_models_api,
    "openrouter_models_api": openrouter_models_api,
}
