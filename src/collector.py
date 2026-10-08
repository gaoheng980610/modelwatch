#!/usr/bin/env python3
"""ModelWatch collector.

Pipeline: seed -> live adapters (merged) -> data/models.json + data/history/<date>.json

Credential-free by design. An adapter whose env var is unset is *skipped*, not
failed, and the seed always loads first - so the dataset is never empty and the
collector runs today with zero accounts, then upgrades itself the moment a key
exists.

Usage:
    python src/collector.py              # collect everything available
    python src/collector.py --dry-run    # show the plan, write nothing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import adapters  # noqa: E402
import monitor  # noqa: E402

DATA = ROOT / "data"
SOURCES = DATA / "sources.json"
MODELS = DATA / "models.json"
HISTORY = DATA / "history"
CHANGES_LOG = DATA / "changes" / "log.json"
TIMEOUT_SECONDS = 30


class MissingCredentials(Exception):
    """An adapter needs an env var that is not set."""


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def http_get_json(adapter: dict) -> dict:
    auth = adapter.get("auth") or {}
    env_name = auth.get("env", "")
    token = os.environ.get(env_name, "") if env_name else ""
    if env_name and not token:
        raise MissingCredentials(env_name)

    headers = {"Accept": "application/json", **(auth.get("extra_headers") or {})}
    if token:
        headers[auth.get("header", "Authorization")] = f"{auth.get('prefix', '')}{token}"

    request = urllib.request.Request(adapter["url"], headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def collect(retrieved_at: str) -> tuple[dict[str, dict], list[str]]:
    """Run every enabled adapter, merging into one id-keyed record map."""
    sources = load_json(SOURCES)
    merged: dict[str, dict] = {}
    log: list[str] = []

    for adapter in sources.get("adapters", []):
        if not adapter.get("enabled", True):
            log.append(f"skip   {adapter['id']} (disabled)")
            continue

        parser = adapters.PARSERS.get(adapter.get("parser", ""))
        if parser is None:
            log.append(f"ERR    {adapter['id']}: unknown parser {adapter.get('parser')!r}")
            continue

        try:
            if adapter["kind"] == "file":
                payload = load_json(ROOT / adapter["path"])
                records = parser(payload, retrieved_at=retrieved_at)
                verb = "load "
            elif adapter["kind"] == "api":
                payload = http_get_json(adapter)
                records = parser(payload, retrieved_at=retrieved_at)
                verb = "fetch"
            else:
                log.append(f"ERR    {adapter['id']}: unknown kind {adapter['kind']!r}")
                continue

            for record in records:
                merged[record["id"]] = adapters.merge_record(merged.get(record["id"]), record)
            log.append(f"{verb}  {adapter['id']}: {len(records)} record(s)")

        except MissingCredentials as exc:
            log.append(f"skip   {adapter['id']} (missing env {exc})")
        except urllib.error.HTTPError as exc:
            log.append(f"ERR    {adapter['id']}: HTTP {exc.code}")
        except Exception as exc:  # a bad source must never abort the whole run
            log.append(f"ERR    {adapter['id']}: {type(exc).__name__}: {exc}")

    return merged, log


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect model data from all available sources.")
    ap.add_argument("--dry-run", action="store_true", help="print the plan without writing files")
    args = ap.parse_args()

    retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    merged, log = collect(retrieved_at)

    for line in log:
        print(line)
    print(f"--- {len(merged)} model(s) after merge")

    if not merged:
        print("refusing to write an empty dataset")
        return 1
    if args.dry_run:
        print("(dry-run: nothing written)")
        return 0

    payload = {
        "meta": {
            "schema_version": "0.1.0",
            "dataset": "modelwatch",
            "generated_at": retrieved_at[:10],
            "as_of": max((m.get("as_of") or "" for m in merged.values()), default=""),
        },
        "models": [merged[key] for key in sorted(merged)],
    }

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    MODELS.write_text(text, encoding="utf-8")
    HISTORY.mkdir(exist_ok=True)
    # Timestamped to the minute, not just the date. Upstream data is live: two
    # runs 26 minutes apart moved 10 input prices. A date-only filename made the
    # second run silently OVERWRITE the first, so those changes were dropped
    # before the log could see them.
    snapshot = HISTORY / f"{retrieved_at[:10]}T{retrieved_at[11:16].replace(':', '')}Z.json"
    snapshot.write_text(text, encoding="utf-8")

    # Append the diff against the previous snapshot to the append-only change log.
    # A no-op on the very first run, which is correct: there is nothing to diff yet.
    snaps = sorted(HISTORY.glob("*.json"))
    if len(snaps) >= 2:
        entry = monitor.append_entry(CHANGES_LOG, snaps[-2], snaps[-1])
        print(f"logged {entry['count']} change(s) {entry['from']} -> {entry['to']}")

    print(f"wrote {MODELS.relative_to(ROOT)} and {snapshot.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
