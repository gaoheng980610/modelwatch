#!/usr/bin/env python3
"""ModelWatch monitor: diff two history snapshots into a change feed.

This is the core of the paid product - "tell me the moment a model I depend on
changes price, limits, or lifecycle." Snapshots are the compounding asset: the
feed is only as valuable as the history behind it.

Usage:
    python src/monitor.py                  # diff the two most recent snapshots
    python src/monitor.py A.json B.json    # diff two specific snapshots
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data" / "history"
CHANGES = ROOT / "data" / "changes"
LOG = CHANGES / "log.json"

# Fields worth waking someone up for.
TRACKED = [
    (("pricing", "input"), "price_input"),
    (("pricing", "output"), "price_output"),
    (("pricing", "cached_input"), "price_cached_input"),
    (("context", "max_input_tokens"), "context_window"),
    (("context", "max_output_tokens"), "max_output"),
    (("lifecycle", "status"), "lifecycle_status"),
]


def _get(record: dict, path: tuple[str, ...]):
    current = record
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def diff(prev: dict, curr: dict) -> list[dict]:
    """Return the list of changes turning snapshot `prev` into `curr`."""
    prev_models = {m["id"]: m for m in prev.get("models", [])}
    curr_models = {m["id"]: m for m in curr.get("models", [])}
    changes: list[dict] = []

    for mid in sorted(curr_models.keys() - prev_models.keys()):
        changes.append({"model": mid, "type": "added", "from": None,
                        "to": curr_models[mid].get("display_name")})
    for mid in sorted(prev_models.keys() - curr_models.keys()):
        changes.append({"model": mid, "type": "removed",
                        "from": prev_models[mid].get("display_name"), "to": None})

    for mid in sorted(prev_models.keys() & curr_models.keys()):
        before, after = prev_models[mid], curr_models[mid]
        for path, label in TRACKED:
            old, new = _get(before, path), _get(after, path)
            if old != new:
                changes.append({"model": mid, "type": label, "from": old, "to": new})

        caps_before = before.get("capabilities") or {}
        caps_after = after.get("capabilities") or {}
        for key in sorted(set(caps_before) | set(caps_after)):
            if caps_before.get(key) != caps_after.get(key):
                changes.append({"model": mid, "type": f"capability:{key}",
                                "from": caps_before.get(key), "to": caps_after.get(key)})

    return changes


def append_entry(log_path: Path, prev_path: Path, curr_path: Path) -> dict:
    """Append the diff between two snapshots to the append-only change log.

    The log is the durable asset: `changes/feed.json` only ever describes the
    latest diff, so without this, a change missed between runs is a change lost.
    Entries are keyed by (from, to) - re-running against the same pair updates
    that entry instead of duplicating it.

    `detected_at` records when WE saw the change, which is not the same as when
    it was true; both are kept.
    """
    prev = json.loads(Path(prev_path).read_text(encoding="utf-8"))
    curr = json.loads(Path(curr_path).read_text(encoding="utf-8"))
    changes = diff(prev, curr)

    log_path = Path(log_path)
    if log_path.exists():
        log = json.loads(log_path.read_text(encoding="utf-8"))
    else:
        log = {"meta": {}, "entries": []}

    key_from, key_to = Path(prev_path).stem, Path(curr_path).stem
    entries = [e for e in log.get("entries", [])
               if not (e.get("from") == key_from and e.get("to") == key_to)]
    entry = {
        "from": key_from, "to": key_to,
        "detected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(changes), "changes": changes,
    }
    entries.append(entry)

    log["entries"] = entries
    log["meta"] = {
        "entries": len(entries),
        "first": entries[0]["from"],
        "latest": entries[-1]["to"],
        "total_changes": sum(e["count"] for e in entries),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    return entry


def snapshots() -> list[Path]:
    return sorted(HISTORY.glob("*.json")) if HISTORY.exists() else []


def main() -> int:
    args = sys.argv[1:]
    if len(args) == 2:
        prev_path, curr_path = Path(args[0]), Path(args[1])
    else:
        snaps = snapshots()
        if len(snaps) < 2:
            print(f"need >= 2 snapshots to diff, found {len(snaps)} in {HISTORY}")
            return 0
        prev_path, curr_path = snaps[-2], snaps[-1]

    prev = json.loads(prev_path.read_text(encoding="utf-8"))
    curr = json.loads(curr_path.read_text(encoding="utf-8"))
    changes = diff(prev, curr)

    print(f"diff {prev_path.name} -> {curr_path.name}: {len(changes)} change(s)")
    for change in changes:
        print(f"  [{change['type']}] {change['model']}: {change['from']} -> {change['to']}")

    CHANGES.mkdir(exist_ok=True)
    feed = {"from": prev_path.stem, "to": curr_path.stem,
            "count": len(changes), "changes": changes}
    (CHANGES / "feed.json").write_text(json.dumps(feed, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {(CHANGES / 'feed.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
