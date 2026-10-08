"""Client tests - no network; the transport is injected.

Run:  python -m unittest discover -s clients/py/tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modelwatch import ModelWatch  # noqa: E402

MODELS = {
    "meta": {"count": 3},
    "models": [
        {"id": "cheap", "provider": "acme", "display_name": "Cheap",
         "pricing": {"input": 1.0, "output": 2.0}},
        {"id": "pricey", "provider": "acme", "display_name": "Pricey",
         "pricing": {"input": 5.0, "output": 50.0}},
        {"id": "unpriced", "provider": "acme", "display_name": "Unpriced",
         "pricing": {"input": None, "output": None}},
    ],
}
CHANGES = {"meta": {}, "changes": [{"model": "pricey", "type": "price_input", "from": 4.0, "to": 5.0}]}


def fake_fetch(url: str):
    if url.endswith("/api/v1/models.json"):
        return MODELS
    if url.endswith("/api/v1/changes.json"):
        return CHANGES
    raise AssertionError(f"unexpected url {url}")


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.mw = ModelWatch(base_url="https://example.test/", fetch=fake_fetch)

    def test_base_url_is_normalized(self):
        self.assertEqual(self.mw.base_url, "https://example.test")

    def test_models(self):
        self.assertEqual(len(self.mw.models()), 3)

    def test_model_lookup_hit_and_miss(self):
        self.assertEqual(self.mw.model("cheap")["display_name"], "Cheap")
        self.assertIsNone(self.mw.model("nope"))

    def test_cheapest_skips_unpriced_and_sorts(self):
        got = [m["id"] for m in self.mw.cheapest(by="input", limit=10)]
        self.assertEqual(got, ["cheap", "pricey"])  # unpriced excluded, ascending

    def test_cheapest_respects_limit_and_provider(self):
        self.assertEqual([m["id"] for m in self.mw.cheapest(limit=1)], ["cheap"])
        self.assertEqual(self.mw.cheapest(provider="nobody"), [])

    def test_changes(self):
        self.assertEqual(self.mw.changes()["changes"][0]["type"], "price_input")


if __name__ == "__main__":
    unittest.main()
