"""ModelWatch client - AI model capabilities, context windows and pricing.

Dependency-free (stdlib only). Reads the public read-only JSON API.

    from modelwatch import ModelWatch
    mw = ModelWatch()                       # or ModelWatch(base_url="...")
    opus = mw.model("claude-opus-5")
    print(opus["pricing"]["input"])         # 5  (USD per million tokens)
    for m in mw.cheapest(by="input", limit=5):
        print(m["display_name"], m["pricing"]["input"])
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Iterable

DEFAULT_BASE_URL = "https://modelwatch.example"

__all__ = ["ModelWatch", "DEFAULT_BASE_URL", "__version__"]
__version__ = "0.1.0"

Fetch = Callable[[str], Any]


def _default_fetch(url: str) -> Any:
    request = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


class ModelWatch:
    """Thin, typed-lite wrapper over the ModelWatch JSON API.

    Pass ``fetch`` to inject a transport (used by the tests, and useful for
    caching or proxying in production).
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL, fetch: Fetch | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._fetch: Fetch = fetch or _default_fetch

    def _get(self, path: str) -> Any:
        return self._fetch(f"{self.base_url}{path}")

    def dataset(self) -> dict:
        """The whole envelope: ``{"meta": ..., "models": [...]}``."""
        return self._get("/api/v1/models.json")

    def models(self) -> list[dict]:
        return self.dataset().get("models", [])

    def model(self, model_id: str) -> dict | None:
        return next((m for m in self.models() if m.get("id") == model_id), None)

    def changes(self) -> dict:
        """Change feed between the two most recent snapshots."""
        return self._get("/api/v1/changes.json")

    def cheapest(self, by: str = "input", limit: int = 10, provider: str | None = None) -> Iterable[dict]:
        """Cheapest models by ``by`` ("input" | "output"); unpriced models skipped."""
        models = self.models()
        if provider:
            models = [m for m in models if m.get("provider") == provider]
        priced = [m for m in models if isinstance((m.get("pricing") or {}).get(by), (int, float))]
        priced.sort(key=lambda m: m["pricing"][by])
        return priced[:limit]
