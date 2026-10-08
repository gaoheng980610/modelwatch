#!/usr/bin/env python3
"""Pipeline tests: parsers, merge rules, and the change monitor.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import adapters  # noqa: E402
import alerts  # noqa: E402
import build_site  # noqa: E402
import monitor  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "anthropic_models_api.json"
FIXTURE_OR = ROOT / "tests" / "fixtures" / "openrouter_models.json"


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_anthropic_adapter_maps_fields(self):
        records = adapters.anthropic_models_api(self.payload, retrieved_at="2026-10-08")
        self.assertEqual({r["id"] for r in records}, {"claude-opus-5", "claude-sonnet-5"})
        opus = next(r for r in records if r["id"] == "claude-opus-5")
        self.assertEqual(opus["context"]["max_input_tokens"], 1000000)
        self.assertEqual(opus["context"]["max_output_tokens"], 128000)
        self.assertEqual(opus["family"], "opus")
        self.assertEqual(opus["provenance"][0]["source_type"], "vendor_api")

    def test_models_api_returns_no_pricing(self):
        opus = adapters.anthropic_models_api(self.payload, retrieved_at="2026-10-08")[0]
        self.assertIsNone(opus["pricing"]["input"])

    def test_merge_keeps_known_price_and_updates_context(self):
        seed = {
            "id": "claude-opus-5", "provider": "anthropic", "display_name": "Claude Opus 5",
            "lifecycle": {"status": "ga", "deprecated_at": None, "retired_at": None, "notice": "Excluded from Priority Tier."},
            "context": {"max_input_tokens": 500000, "max_output_tokens": 64000},
            "pricing": {"currency": "USD", "unit": "per_mtok", "input": 5.0, "output": 25.0,
                        "cached_input": None, "cache_write": None, "notes": None},
            "capabilities": {"vision": True},
            "as_of": "2026-06-24", "confidence": "verified",
            "provenance": [{"source_url": "seed://manual", "source_type": "manual", "retrieved_at": "2026-06-24"}],
        }
        incoming = next(r for r in adapters.anthropic_models_api(self.payload, retrieved_at="2026-10-08")
                        if r["id"] == "claude-opus-5")
        merged = adapters.merge_record(seed, incoming)

        self.assertEqual(merged["pricing"]["input"], 5.0)          # null never erases a known price
        self.assertEqual(merged["context"]["max_input_tokens"], 1000000)  # fresh value wins
        self.assertEqual(merged["lifecycle"]["notice"], "Excluded from Priority Tier.")  # preserved
        self.assertEqual(len(merged["provenance"]), 2)             # provenance accumulates
        self.assertEqual(merged["as_of"], "2026-10-08")            # newest as_of

    def test_merge_from_none_returns_incoming(self):
        incoming = adapters.anthropic_models_api(self.payload, retrieved_at="2026-10-08")[0]
        self.assertEqual(adapters.merge_record(None, incoming)["id"], "claude-opus-5")


def _snap(models):
    return {"models": models}


def _model(mid, **over):
    base = {"id": mid, "display_name": mid.upper(),
            "pricing": {"input": 1.0, "output": 2.0, "cached_input": None},
            "context": {"max_input_tokens": 1000, "max_output_tokens": 100},
            "lifecycle": {"status": "ga"}, "capabilities": {"vision": True}}
    base.update(over)
    return base


class MonitorTests(unittest.TestCase):
    def test_detects_price_and_lifecycle_change(self):
        prev = _snap([_model("m")])
        curr = _snap([_model("m", pricing={"input": 2.0, "output": 2.0, "cached_input": None},
                             lifecycle={"status": "deprecated"})])
        kinds = {c["type"] for c in monitor.diff(prev, curr)}
        self.assertIn("price_input", kinds)
        self.assertIn("lifecycle_status", kinds)

    def test_detects_added_and_removed(self):
        prev = _snap([_model("a")])
        curr = _snap([_model("b")])
        kinds = {c["type"] for c in monitor.diff(prev, curr)}
        self.assertEqual(kinds, {"added", "removed"})

    def test_no_change_is_empty(self):
        snap = _snap([_model("m")])
        self.assertEqual(monitor.diff(snap, snap), [])

    def test_detects_context_and_capability_change(self):
        prev = _snap([_model("m")])
        curr = _snap([_model("m", context={"max_input_tokens": 2000, "max_output_tokens": 100},
                             capabilities={"vision": False})])
        kinds = {c["type"] for c in monitor.diff(prev, curr)}
        self.assertIn("context_window", kinds)
        self.assertIn("capability:vision", kinds)


class OpenRouterTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE_OR.read_text(encoding="utf-8"))

    def test_maps_price_context_and_capabilities(self):
        records = adapters.openrouter_models_api(self.payload, retrieved_at="2026-10-08")
        opus = next(r for r in records if r["id"] == "claude-opus-5")
        self.assertEqual(opus["provider"], "anthropic")
        self.assertEqual(opus["pricing"]["input"], 5.0)     # 0.000005 per token -> $5 / MTok
        self.assertEqual(opus["pricing"]["output"], 25.0)
        self.assertEqual(opus["context"]["max_input_tokens"], 1000000)
        self.assertEqual(opus["context"]["max_output_tokens"], 128000)
        self.assertTrue(opus["capabilities"]["vision"])
        self.assertTrue(opus["capabilities"]["tool_use"])
        self.assertEqual(opus["confidence"], "partly_verified")

    def test_skips_colon_variant_ids(self):
        ids = {r["id"] for r in adapters.openrouter_models_api(self.payload, retrieved_at="2026-10-08")}
        self.assertEqual(ids, {"claude-opus-5", "gpt-6-luna-pro"})  # :batch dropped

    def test_variable_pricing_sentinel_becomes_null(self):
        payload = {"data": [{"id": "acme/auto", "name": "Auto", "context_length": 1000,
                             "pricing": {"prompt": "-1", "completion": "-1"},
                             "architecture": {}, "supported_parameters": []}]}
        rec = adapters.openrouter_models_api(payload, retrieved_at="2026-10-08")[0]
        self.assertIsNone(rec["pricing"]["input"])
        self.assertIsNone(rec["pricing"]["output"])

    def test_skips_openrouter_router_pseudo_models(self):
        payload = {"data": [{"id": "openrouter/auto", "name": "Auto Router", "context_length": 1000,
                             "pricing": {"prompt": "0.000001", "completion": "0.000001"},
                             "architecture": {}, "supported_parameters": []}]}
        self.assertEqual(adapters.openrouter_models_api(payload, retrieved_at="2026-10-08"), [])

    def test_normalizes_dotted_versions_to_match_first_party_ids(self):
        payload = {"data": [{"id": "anthropic/claude-opus-4.8", "name": "Anthropic: Claude Opus 4.8",
                             "context_length": 1000000, "pricing": {"prompt": "0.000005", "completion": "0.000025"},
                             "architecture": {}, "supported_parameters": []}]}
        rec = adapters.openrouter_models_api(payload, retrieved_at="2026-10-08")[0]
        self.assertEqual(rec["id"], "claude-opus-4-8")  # matches the seed's id

    def test_maps_modalities_and_efforts(self):
        recs = adapters.openrouter_models_api(self.payload, retrieved_at="2026-10-08")
        opus = next(r for r in recs if r["id"] == "claude-opus-5")
        self.assertEqual(opus["capabilities"]["modalities_in"], ["text", "image"])
        self.assertEqual(opus["capabilities"]["effort_levels"], ["low", "high"])

    def test_effort_levels_are_canonically_ordered(self):
        payload = {"data": [{"id": "acme/x", "name": "X", "context_length": 1,
                             "pricing": {"prompt": "0.000001", "completion": "0.000001"},
                             "architecture": {"input_modalities": ["text"]},
                             "supported_parameters": [],
                             "reasoning": {"supported_efforts": ["max", "low", "high"]}}]}
        rec = adapters.openrouter_models_api(payload, retrieved_at="2026-10-08")[0]
        self.assertEqual(rec["capabilities"]["effort_levels"], ["low", "high", "max"])

    def test_maps_sampling_from_supported_parameters(self):
        def parse(supported, **extra):
            payload = {"data": [{"id": "acme/x", "name": "X", "context_length": 1,
                                 "pricing": {"prompt": "0.000001", "completion": "0.000001"},
                                 "architecture": {"input_modalities": ["text"]},
                                 "supported_parameters": supported, **extra}]}
            return adapters.openrouter_models_api(payload, retrieved_at="2026-10-08")[0]

        self.assertTrue(parse(["temperature", "tools"])["capabilities"]["sampling"])
        self.assertTrue(parse(["top_p"])["capabilities"]["sampling"])
        self.assertFalse(parse(["tools"])["capabilities"]["sampling"])

    def test_open_weights_is_the_exact_repo_id_never_inferred(self):
        payload = {"data": [{"id": "acme/x", "name": "X", "context_length": 1,
                             "pricing": {"prompt": "0.000001", "completion": "0.000001"},
                             "architecture": {}, "supported_parameters": [],
                             "hugging_face_id": "acme/x-7b"}]}
        rec = adapters.openrouter_models_api(payload, retrieved_at="2026-10-08")[0]
        self.assertEqual(rec["hugging_face_id"], "acme/x-7b")
        # absent means unknown, not "closed"
        payload["data"][0].pop("hugging_face_id")
        self.assertIsNone(adapters.openrouter_models_api(payload, retrieved_at="2026-10-08")[0]["hugging_face_id"])

    def test_maps_tiered_pricing_and_sorts_bands(self):
        """Regression: `overrides` was dropped, so ~62 models showed a single flat
        price even though they charge more above a prompt-size threshold."""
        payload = {"data": [{"id": "acme/x", "name": "X", "context_length": 1,
                             "architecture": {}, "supported_parameters": [],
                             "pricing": {"prompt": "0.0000001", "completion": "0.0000005",
                                         "overrides": [
                                             {"min_prompt_tokens": 200000, "prompt": "0.0000004",
                                              "completion": "0.000002"},
                                             {"min_prompt_tokens": 100000, "prompt": "0.0000002",
                                              "completion": "0.000001"}]}}]}
        tiers = adapters.openrouter_models_api(payload, retrieved_at="2026-10-08")[0]["pricing"]["tiers"]
        self.assertEqual([t["above_input_tokens"] for t in tiers], [100000, 200000])
        self.assertEqual(tiers[0]["input"], 0.2)
        self.assertEqual(tiers[1]["input"], 0.4)

    def test_no_overrides_means_no_tiers(self):
        payload = {"data": [{"id": "acme/y", "name": "Y", "context_length": 1,
                             "architecture": {}, "supported_parameters": [],
                             "pricing": {"prompt": "0.000001", "completion": "0.000001"}}]}
        self.assertIsNone(
            adapters.openrouter_models_api(payload, retrieved_at="2026-10-08")[0]["pricing"]["tiers"])


class MergeTrustTests(unittest.TestCase):
    @staticmethod
    def _rec(conf, **over):
        base = {"id": "m", "provider": "p", "display_name": "M", "confidence": conf,
                "lifecycle": {"status": "ga"},
                "context": {"max_input_tokens": None, "max_output_tokens": None},
                "pricing": {"input": None, "output": None}, "capabilities": {},
                "as_of": "2026-01-01",
                "provenance": [{"source_url": "a", "source_type": "manual", "retrieved_at": "2026-01-01"}]}
        base.update(over)
        return base

    def test_third_party_cannot_overwrite_verified(self):
        verified = self._rec("verified", pricing={"input": 5.0, "output": None},
                             context={"max_input_tokens": 1000, "max_output_tokens": None})
        third = self._rec("partly_verified", pricing={"input": 9.9, "output": None},
                          context={"max_input_tokens": 9999, "max_output_tokens": None})
        merged = adapters.merge_record(verified, third)
        self.assertEqual(merged["pricing"]["input"], 5.0)              # protected
        self.assertEqual(merged["context"]["max_input_tokens"], 1000)
        self.assertEqual(merged["confidence"], "verified")             # not downgraded

    def test_third_party_fills_nulls(self):
        verified = self._rec("verified")
        third = self._rec("partly_verified",
                          context={"max_input_tokens": 8888, "max_output_tokens": 123})
        merged = adapters.merge_record(verified, third)
        self.assertEqual(merged["context"]["max_input_tokens"], 8888)
        self.assertEqual(merged["context"]["max_output_tokens"], 123)
        self.assertEqual(merged["confidence"], "verified")

    def test_lower_trust_does_not_add_pricing_fields_to_priced_record(self):
        verified = self._rec("verified", pricing={"input": 5.0, "output": 25.0})
        third = self._rec("partly_verified",
                          pricing={"input": None, "output": None, "cached_input": 0.5})
        merged = adapters.merge_record(verified, third)
        self.assertIsNone(merged["pricing"].get("cached_input"))  # no silent mixing

    def test_price_conflict_is_surfaced_not_merged(self):
        verified = self._rec("verified", pricing={"input": 5.0, "output": 25.0})
        third = self._rec("partly_verified", pricing={"input": 6.0, "output": 25.0},
                          provenance=[{"source_url": "https://or", "source_type": "third_party",
                                       "retrieved_at": "2026-10-08"}])
        merged = adapters.merge_record(verified, third)
        self.assertEqual(merged["pricing"]["input"], 5.0)          # ours kept
        self.assertEqual(merged["conflicts"][0]["disagreement"]["input"]["theirs"], 6.0)

    def test_lower_trust_fills_price_when_record_is_unpriced(self):
        verified = self._rec("verified", pricing={"input": None, "output": None})
        third = self._rec("partly_verified", pricing={"input": 3.0, "output": 9.0})
        merged = adapters.merge_record(verified, third)
        self.assertEqual(merged["pricing"]["input"], 3.0)          # nothing to protect


class TrendSeriesTests(unittest.TestCase):
    """The month series must be continuous and gap-filled — a missing month would
    compress time and make the release cadence look smoother than it is."""

    def test_fills_empty_months_with_zero(self):
        models = [{"released": "2026-01-05"}, {"released": "2026-01-20"}, {"released": "2026-03-01"}]
        self.assertEqual(build_site.monthly_releases(models),
                         [("2026-01", 2), ("2026-02", 0), ("2026-03", 1)])

    def test_rolls_over_the_year_boundary(self):
        models = [{"released": "2025-11-01"}, {"released": "2026-02-01"}]
        self.assertEqual([m for m, _ in build_site.monthly_releases(models)],
                         ["2025-11", "2025-12", "2026-01", "2026-02"])

    def test_ignores_undated_models(self):
        models = [{"released": None}, {"released": "2026-02-01"}]
        self.assertEqual(build_site.monthly_releases(models), [("2026-02", 1)])

    def test_empty_input(self):
        self.assertEqual(build_site.monthly_releases([]), [])


class RecentModelsTests(unittest.TestCase):
    """"New" must mean dated-and-recent, never assumed."""

    def test_excludes_undated_and_old(self):
        today = date.today()
        models = [{"id": "fresh", "released": (today - timedelta(days=10)).isoformat()},
                  {"id": "old", "released": (today - timedelta(days=400)).isoformat()},
                  {"id": "undated", "released": None}]
        self.assertEqual([m["id"] for m in build_site.recent_models(models)], ["fresh"])

    def test_sorted_newest_first(self):
        today = date.today()
        models = [{"id": "older", "released": (today - timedelta(days=40)).isoformat()},
                  {"id": "newer", "released": (today - timedelta(days=5)).isoformat()}]
        self.assertEqual([m["id"] for m in build_site.recent_models(models)], ["newer", "older"])

    def test_window_boundary_is_inclusive(self):
        edge = (date.today() - timedelta(days=build_site.RECENT_DAYS)).isoformat()
        self.assertEqual(len(build_site.recent_models([{"id": "edge", "released": edge}])), 1)


class ChangeLogTests(unittest.TestCase):
    """The log is append-only and keyed by (from, to): re-running a pair updates
    that entry rather than duplicating it. Uses temp dirs - never touches data/."""

    @staticmethod
    def _snap(path: Path, price: float) -> None:
        path.write_text(json.dumps({"models": [
            {"id": "m", "display_name": "M", "pricing": {"input": price, "output": None},
             "context": {"max_input_tokens": 1000, "max_output_tokens": None},
             "lifecycle": {"status": "ga"}, "capabilities": {}}]}), encoding="utf-8")

    def test_appends_entry_and_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            prev, curr, log = d / "2026-01-01.json", d / "2026-01-02.json", d / "log.json"
            self._snap(prev, 1.0)
            self._snap(curr, 2.0)
            entry = monitor.append_entry(log, prev, curr)
            self.assertEqual((entry["from"], entry["to"], entry["count"]),
                             ("2026-01-01", "2026-01-02", 1))
            written = json.loads(log.read_text(encoding="utf-8"))
            self.assertEqual(written["meta"]["entries"], 1)
            self.assertEqual(written["meta"]["total_changes"], 1)
            self.assertEqual(written["meta"]["latest"], "2026-01-02")

    def test_rerunning_the_same_pair_updates_instead_of_duplicating(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            prev, curr, log = d / "2026-01-01.json", d / "2026-01-02.json", d / "log.json"
            self._snap(prev, 1.0)
            self._snap(curr, 2.0)
            monitor.append_entry(log, prev, curr)
            monitor.append_entry(log, prev, curr)
            self.assertEqual(json.loads(log.read_text(encoding="utf-8"))["meta"]["entries"], 1)

    def test_accumulates_across_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            a, b, c = d / "d1.json", d / "d2.json", d / "d3.json"
            log = d / "log.json"
            self._snap(a, 1.0)
            self._snap(b, 2.0)
            self._snap(c, 3.0)
            monitor.append_entry(log, a, b)
            monitor.append_entry(log, b, c)
            meta = json.loads(log.read_text(encoding="utf-8"))["meta"]
            self.assertEqual(meta["entries"], 2)
            self.assertEqual(meta["total_changes"], 2)
            self.assertEqual((meta["first"], meta["latest"]), ("d1", "d3"))

    def test_no_change_records_a_zero_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            prev, curr, log = d / "d1.json", d / "d2.json", d / "log.json"
            self._snap(prev, 1.0)
            self._snap(curr, 1.0)
            entry = monitor.append_entry(log, prev, curr)
            self.assertEqual(entry["count"], 0)  # honest: a run with nothing to report


class AnalyticsTests(unittest.TestCase):
    """These aggregates are published as claims, so the arithmetic is tested."""

    def test_median_odd_even_and_empty(self):
        self.assertEqual(build_site.median([1, 2, 3]), 2)
        self.assertEqual(build_site.median([1, 2, 3, 4]), 2.5)
        self.assertIsNone(build_site.median([]))

    def test_context_by_year_medians_and_skips_undated(self):
        models = [
            {"released": "2024-01-01", "context": {"max_input_tokens": 1000}},
            {"released": "2024-06-01", "context": {"max_input_tokens": 3000}},
            {"released": "2024-09-01", "context": {"max_input_tokens": 2000}},
            {"released": None, "context": {"max_input_tokens": 99999}},       # undated: excluded
            {"released": "2025-01-01", "context": {"max_input_tokens": None}},  # unknown: excluded
        ]
        self.assertEqual(build_site.context_by_year(models), [("2024", 2000)])

    def test_modality_adoption_is_a_percentage(self):
        models = [
            {"released": "2024-01-01", "capabilities": {"modalities_in": ["text", "image"]}},
            {"released": "2024-02-01", "capabilities": {"modalities_in": ["text"]}},
        ]
        self.assertEqual(build_site.modality_adoption(models), [("2024", 50)])

    def test_price_distribution_buckets_cover_the_range(self):
        models = [{"pricing": {"input": p}} for p in [0, 0.25, 0.75, 3, 10, 100]]
        dist = dict(build_site.price_distribution(models))
        self.assertEqual(sum(dist.values()), 6)          # every priced model is in exactly one bucket
        self.assertEqual(dist["Free"], 1)
        self.assertEqual(dist["≤ $0.50"], 1)
        self.assertEqual(dist["over $15"], 1)


ATOM = "{http://www.w3.org/2005/Atom}"


class FeedTests(unittest.TestCase):
    """A malformed feed fails silently in most readers, so parse it back."""

    @staticmethod
    def _models():
        return [
            {"id": "a", "provider": "acme", "display_name": "A", "released": "2026-01-01",
             "context": {"max_input_tokens": 1000, "max_output_tokens": None},
             "pricing": {"input": 1.0, "output": None}},
            {"id": "b", "provider": "acme", "display_name": "B", "released": "2026-03-01",
             "context": {"max_input_tokens": 2000, "max_output_tokens": None},
             "pricing": {"input": 2.0, "output": None}},
            {"id": "c", "provider": "acme", "display_name": "C", "released": None,
             "context": {"max_input_tokens": 500, "max_output_tokens": None},
             "pricing": {"input": 0.5, "output": None}},
        ]

    def test_is_well_formed_and_newest_first(self):
        root = ET.fromstring(build_site.build_feed(self._models()))
        titles = [e.findtext(ATOM + "title") for e in root.findall(ATOM + "entry")]
        self.assertEqual(len(titles), 2)                  # undated model excluded
        self.assertEqual(titles[0], "B — Acme")           # newest first
        self.assertEqual(root.findtext(ATOM + "updated"), "2026-03-01T00:00:00Z")

    def test_escapes_special_characters(self):
        models = [{"id": "x", "provider": "acme", "display_name": "A & B <test>",
                   "released": "2026-01-01", "context": {"max_input_tokens": 1},
                   "pricing": {"input": None}}]
        root = ET.fromstring(build_site.build_feed(models))   # parses => escaping is correct
        self.assertEqual(root.findtext(ATOM + "entry/" + ATOM + "title"), "A & B <test> — Acme")

    def test_empty_dataset_still_produces_a_valid_feed(self):
        root = ET.fromstring(build_site.build_feed([]))
        self.assertEqual(len(root.findall(ATOM + "entry")), 0)
        self.assertEqual(root.tag, ATOM + "feed")


class BenchmarkTests(unittest.TestCase):
    """Benchmark blocks arrive in two shapes and are third-party data, so they are
    normalized into their own key rather than mixed into first-party fields."""

    def test_normalizes_both_shapes_and_drops_non_numeric(self):
        out = adapters._benchmarks({
            "artificial_analysis": {"intelligence_index": 50.8, "coding_index": 78, "note": "x"},
            "design_arena": [{"arena": "agents", "category": "fullstack",
                              "elo": 1305, "win_rate": 57.3, "rank": 4}]})
        self.assertEqual(out["artificial_analysis"], {"intelligence_index": 50.8, "coding_index": 78})
        self.assertEqual(out["design_arena"][0]["elo"], 1305)

    def test_arena_rows_keep_only_known_keys(self):
        out = adapters._benchmarks({"design_arena": [
            {"arena": "a", "category": "c", "elo": 1, "win_rate": 2, "rank": 3, "junk": 9}]})
        self.assertEqual(set(out["design_arena"][0]),
                         {"arena", "category", "elo", "win_rate", "rank"})

    def test_absent_or_wrong_type_yields_none(self):
        for raw in (None, "nope", {}, [], {"artificial_analysis": "nope"}):
            self.assertIsNone(adapters._benchmarks(raw))

    def test_intelligence_index_extraction(self):
        self.assertEqual(build_site.intelligence_index(
            {"benchmarks": {"artificial_analysis": {"intelligence_index": 42}}}), 42)
        self.assertIsNone(build_site.intelligence_index({}))
        self.assertIsNone(build_site.intelligence_index({"benchmarks": {}}))

    def test_first_party_share_counts_records_not_provenance_entries(self):
        """Regression: counting 'has a third-party entry' returns ~100% after merging,
        because every merged record carries both. Count records a vendor backs."""
        models = [
            {"provenance": [{"source_type": "vendor_docs"}, {"source_type": "third_party"}]},
            {"provenance": [{"source_type": "third_party"}]},
            {"provenance": [{"source_type": "manual"}]},
        ]
        self.assertEqual(build_site.first_party_share(models), (2, 3))

    def test_report_states_the_first_party_count_not_its_complement(self):
        """Regression: unpacking the tuple with swapped names rendered a confidently
        inverted sentence (363 first-party when the truth was 9). Whitespace is
        normalised first — the template wraps lines, so a raw substring match would
        fail regardless of whether the code is correct."""
        data = json.loads((ROOT / "data" / "models.json").read_text(encoding="utf-8"))
        html = re.sub(r"\s+", " ", build_site.build_report(data["models"], data["meta"]))
        fp, total = build_site.first_party_share(data["models"])
        self.assertIn(f"{fp} of {total} records are backed by first-party", html)
        self.assertNotIn(f"{total - fp} of {total} records are backed by first-party", html)


class AlertTests(unittest.TestCase):
    """Severity is derived from the *direction* of a change, not the field name:
    a price rise costs money, a price fall is good news, a shrinking context
    window can break a caller."""

    ENTRIES = [{
        "from": "d1", "to": "d2", "detected_at": "2026-01-02T00:00:00Z",
        "changes": [
            {"model": "a", "type": "price_input", "from": 10.0, "to": 12.0},
            {"model": "b", "type": "price_input", "from": 10.0, "to": 5.0},
            {"model": "a", "type": "lifecycle_status", "from": "ga", "to": "deprecated"},
            {"model": "c", "type": "removed", "from": "C", "to": None},
        ]}]

    def test_severity_reflects_direction(self):
        self.assertEqual(alerts.severity_for({"type": "price_input", "from": 10, "to": 12}), "warning")
        self.assertEqual(alerts.severity_for({"type": "price_input", "from": 10, "to": 5}), "info")
        self.assertEqual(alerts.severity_for({"type": "context_window", "from": 1000, "to": 500}), "warning")
        self.assertEqual(alerts.severity_for({"type": "context_window", "from": 500, "to": 1000}), "info")
        self.assertEqual(alerts.severity_for({"type": "lifecycle_status", "to": "retired"}), "critical")
        self.assertEqual(alerts.severity_for({"type": "removed"}), "critical")

    def test_watchlist_filters_to_the_watched_model(self):
        self.assertEqual({x["model"] for x in alerts.select_alerts(self.ENTRIES, ["a"])}, {"a"})

    def test_star_watches_everything(self):
        self.assertEqual(len(alerts.select_alerts(self.ENTRIES, ["*"])), 4)

    def test_min_price_change_pct_drops_small_moves_only(self):
        got = alerts.select_alerts(self.ENTRIES, ["*"], min_price_change_pct=25)
        kinds = [(x["model"], x["type"]) for x in got]
        self.assertIn(("b", "price_input"), kinds)        # 50% fall: kept
        self.assertNotIn(("a", "price_input"), kinds)     # 20% rise: dropped
        self.assertIn(("a", "lifecycle_status"), kinds)   # non-price types unaffected

    def test_types_restriction(self):
        got = alerts.select_alerts(self.ENTRIES, ["*"], types=["lifecycle_status"])
        self.assertEqual([x["type"] for x in got], ["lifecycle_status"])

    def test_newest_snapshot_pair_first(self):
        entries = [
            {"from": "d1", "to": "d2", "detected_at": "A",
             "changes": [{"model": "a", "type": "added", "from": None, "to": "A"}]},
            {"from": "d2", "to": "d3", "detected_at": "B",
             "changes": [{"model": "a", "type": "removed", "from": "A", "to": None}]},
        ]
        self.assertEqual([x["detected_at"] for x in alerts.select_alerts(entries, ["*"])], ["B", "A"])

    def test_describe_names_the_direction_and_percentage(self):
        self.assertEqual(
            alerts.describe({"model": "x", "type": "price_input", "from": 10.0, "to": 12.0}),
            "x input price rose from $10.00 to $12.00 (20%)")

    def test_describe_reads_like_a_sentence_not_a_diff(self):
        """Regression: context changes rendered as 'context_window ... 400000 to 200000'."""
        self.assertEqual(
            alerts.describe({"model": "m", "type": "context_window", "from": 400000, "to": 200000}),
            "m context window shrank from 400K to 200K")
        self.assertEqual(
            alerts.describe({"model": "m", "type": "max_output", "from": 8000, "to": 16000}),
            "m max output grew from 8K to 16K")

    def test_empty_log_is_not_an_error(self):
        self.assertEqual(alerts.select_alerts([], ["*"]), [])

    def test_fixture_log_is_wired_up_end_to_end(self):
        """Keeps tests/fixtures/sample-changelog.json honest — the CLI demo reads it."""
        entries = alerts.load_log(ROOT / "tests" / "fixtures" / "sample-changelog.json")
        self.assertEqual(len(alerts.select_alerts(entries, ["*"])), 3)
        self.assertEqual(len(alerts.select_alerts(entries, ["claude-opus-5"])), 1)
        self.assertEqual(
            [a["severity"] for a in alerts.select_alerts(entries, ["*"])].count("warning"), 2)

    # ---- delivery payloads -------------------------------------------------

    def _selected(self):
        return alerts.select_alerts(self.ENTRIES, ["*"])

    def test_email_subject_leads_with_the_critical_count(self):
        mail = alerts.build_email(self._selected(), ["*"])
        self.assertIn("1 critical", mail["subject"])
        self.assertEqual(mail["count"], 4)
        self.assertEqual(len(mail["text"].splitlines()), 4)

    def test_email_escapes_html_in_messages(self):
        evil = [{"model": "x", "type": "added", "severity": "info",
                 "message": "<script>alert(1)</script>", "detected_at": "d"}]
        rendered = alerts.build_email(evil, ["*"])["html"]
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_slack_payload_shape(self):
        payload = alerts.build_slack(self._selected())
        self.assertEqual(payload["blocks"][0]["type"], "header")
        self.assertEqual(len(payload["blocks"]), 2)
        self.assertIn("4 change(s)", payload["text"])
        self.assertIn(":rotating_light:", payload["text"])   # the critical one is flagged

    def test_webhook_payload_shape(self):
        payload = alerts.build_webhook(alerts.select_alerts(self.ENTRIES, ["a"]), ["a"])
        self.assertEqual(payload["source"], "modelwatch")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["watching"], ["a"])
        self.assertRegex(payload["generated_at"], r"^\d{4}-\d{2}-\d{2}T")

    def test_empty_alert_set_still_produces_sendable_payloads(self):
        mail = alerts.build_email([], ["*"])
        self.assertEqual(mail["count"], 0)
        self.assertIn("No changes", mail["text"])
        self.assertEqual(len(alerts.build_slack([])["blocks"]), 1)    # header only, no body block


if __name__ == "__main__":
    unittest.main()
