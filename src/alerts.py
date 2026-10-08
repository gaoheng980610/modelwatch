#!/usr/bin/env python3
"""ModelWatch alerts: turn the change log into alerts for a watchlist.

This is the logic behind the paid Monitor tier. It is deliberately a pure
function over the log - delivery (email, webhook, Slack) is infrastructure and is
somebody else's problem; deciding *what* deserves to wake someone up is the
product.

    python src/alerts.py --watch watchlist.json
    python src/alerts.py --all --json
    python src/alerts.py --model claude-opus-5 --fail-if-alerts   # for cron

Watchlist format:

    {
      "models": ["claude-opus-5", "gpt-6-luna-pro", "*"],
      "minPriceChangePct": 10,        // optional: ignore smaller price moves
      "types": ["price_input", "lifecycle_status"]   // optional: restrict
    }
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "data" / "changes" / "log.json"

# Severity is what a human acts on, so it is derived from the *direction* of the
# change, not from the field name alone.
SEVERITY = {
    "retired": "critical",
    "removed": "critical",
    "deprecated": "warning",
    "price_input": "warning",     # direction-adjusted below
    "price_output": "warning",
    "price_cached_input": "warning",
    "context_window": "warning",
    "max_output": "warning",
    "added": "info",
    "lifecycle_status": "warning",
}


def _pct_change(old, new) -> float | None:
    if not isinstance(old, (int, float)) or not isinstance(new, (int, float)) or old == 0:
        return None
    return abs(new - old) / abs(old) * 100


def severity_for(change: dict) -> str:
    kind = change.get("type", "")
    old, new = change.get("from"), change.get("to")

    if kind in ("lifecycle_status",) and new in ("retired", "deprecated"):
        return SEVERITY[new]
    if kind.startswith("price_"):
        # a rise costs money; a fall is good news
        if isinstance(old, (int, float)) and isinstance(new, (int, float)):
            return "warning" if new > old else "info"
        return "info"
    if kind in ("context_window", "max_output"):
        if isinstance(old, (int, float)) and isinstance(new, (int, float)):
            return "warning" if new < old else "info"   # a shrinking window can break callers
        return "info"
    return SEVERITY.get(kind, "info")


def _money(v) -> str:
    return f"${v:,.2f}" if isinstance(v, (int, float)) else str(v)


def _toks(v) -> str:
    if not isinstance(v, (int, float)):
        return str(v)
    if v >= 1_000_000:
        return f"{v / 1_000_000:g}M"
    if v >= 1_000:
        return f"{v / 1_000:g}K"
    return str(int(v))


# A notification should read like a sentence, not like a diff.
PRICE_FIELDS = {"price_input": "input price", "price_output": "output price",
                "price_cached_input": "cached input price", "price_cache_write": "cache-write price"}
SIZE_FIELDS = {"context_window": "context window", "max_output": "max output"}


def describe(change: dict) -> str:
    model = change.get("model", "?")
    kind = change.get("type", "change")
    old, new = change.get("from"), change.get("to")

    if kind == "added":
        return f"{model} appeared"
    if kind == "removed":
        return f"{model} disappeared from the index"
    if kind == "lifecycle_status":
        return f"{model} is now {new}" + (f" (was {old})" if old else "")
    if kind in PRICE_FIELDS:
        pct = _pct_change(old, new)
        numeric = isinstance(old, (int, float)) and isinstance(new, (int, float))
        tail = f" ({pct:.0f}%)" if pct is not None else ""
        return (f"{model} {PRICE_FIELDS[kind]} {'rose' if numeric and new > old else 'fell'} "
                f"from {_money(old)} to {_money(new)}{tail}")
    if kind in SIZE_FIELDS:
        numeric = isinstance(old, (int, float)) and isinstance(new, (int, float))
        return (f"{model} {SIZE_FIELDS[kind]} {'shrank' if numeric and new < old else 'grew'} "
                f"from {_toks(old)} to {_toks(new)}")
    if kind.startswith("capability:"):
        return f"{model} capability {kind.split(':', 1)[1]} changed from {old} to {new}"
    return f"{model} {kind} changed from {old} to {new}"


def matches(model_id: str, watchlist: list[str]) -> bool:
    return any(entry == "*" or entry == model_id for entry in watchlist)


def select_alerts(entries: list[dict], watchlist: list[str], *,
                  types: list[str] | None = None,
                  min_price_change_pct: float | None = None) -> list[dict]:
    """Flatten the log into alerts, newest first."""
    alerts: list[dict] = []
    for entry in entries:
        for change in entry.get("changes", []):
            if not matches(change.get("model", ""), watchlist):
                continue
            kind = change.get("type", "")
            if types and not any(kind == t or kind.startswith(f"{t}:") for t in types):
                continue
            if min_price_change_pct is not None and kind.startswith("price_"):
                pct = _pct_change(change.get("from"), change.get("to"))
                if pct is None or pct < min_price_change_pct:
                    continue
            alerts.append({
                "model": change.get("model"),
                "type": kind,
                "from": change.get("from"),
                "to": change.get("to"),
                "severity": severity_for(change),
                "detected_at": entry.get("detected_at"),
                "between": [entry.get("from"), entry.get("to")],
                "message": describe(change),
            })
    return list(reversed(alerts))          # newest snapshot pair first


def load_watchlist(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):             # bare list of ids is also accepted
        return {"models": data}
    return data


def load_log(path: Path = LOG) -> list[dict]:
    if not Path(path).exists():
        return []
    return json.loads(Path(path).read_text(encoding="utf-8")).get("entries", [])


def build_email(alerts: list[dict], watching: list[str]) -> dict:
    """An email payload — subject, html, text. Sending is infrastructure; the
    message is the product. A critical change leads the subject line, because
    that is the only part most people read."""
    crit = [a for a in alerts if a["severity"] == "critical"]
    subject = (f"[ModelWatch] {len(crit)} critical change(s) to models you watch" if crit
               else f"[ModelWatch] {len(alerts)} change(s) to models you watch")
    rows = "".join(
        f'<tr><td style="padding:6px 10px;border-bottom:1px solid #eee">'
        f'{html.escape(a["severity"])}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #eee">{html.escape(a["message"])}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #eee;color:#666;font-size:12px">'
        f'{html.escape(str(a.get("detected_at") or ""))}</td></tr>' for a in alerts)
    body = ("<p>No changes.</p>" if not alerts else
            '<table style="border-collapse:collapse;font:14px system-ui,sans-serif">'
            f"<tbody>{rows}</tbody></table>")
    html_body = (
        '<div style="font:15px system-ui,sans-serif;color:#111;max-width:640px">'
        f"<h2 style=\"margin:0 0 4px\">{html.escape(subject)}</h2>"
        '<p style="color:#555;margin:0 0 14px">Detected by ModelWatch. Every figure on the site '
        "links to the source it came from.</p>"
        f"{body}"
        '<p style="color:#888;font-size:12px;margin-top:18px">You are getting this because these '
        f"models are on your watchlist ({html.escape(', '.join(watching))}). "
        "Remove one and the alerts stop.</p></div>")
    text_body = "\n".join(f"[{a['severity'].upper()}] {a['message']}" for a in alerts) or "No changes."
    return {"subject": subject, "html": html_body, "text": text_body, "count": len(alerts)}


SLACK_EMOJI = {"critical": ":rotating_light:", "warning": ":warning:", "info": ":information_source:"}


def build_slack(alerts: list[dict]) -> dict:
    """A Slack incoming-webhook payload (Block Kit)."""
    header = f"ModelWatch: {len(alerts)} change(s)"
    lines = "\n".join(f"{SLACK_EMOJI.get(a['severity'], '')} {a['message']}" for a in alerts)
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": header}}]
    if alerts:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": lines[:2900]}})
    return {"text": header if not alerts else f"{header}\n{lines}", "blocks": blocks}


def build_webhook(alerts: list[dict], watching: list[str]) -> dict:
    """A generic JSON payload for any other consumer."""
    return {
        "source": "modelwatch",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "watching": watching,
        "count": len(alerts),
        "alerts": alerts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Turn the change log into alerts for a watchlist.")
    ap.add_argument("--watch", type=Path, help="watchlist JSON file")
    ap.add_argument("--model", action="append", default=[], help="a model id to watch (repeatable)")
    ap.add_argument("--all", action="store_true", help="watch every model")
    ap.add_argument("--log", type=Path, default=LOG)
    ap.add_argument("--format", choices=["text", "json", "email", "slack", "webhook"], default="text",
                    help="output shape; email/slack/webhook are ready-to-send payloads")
    ap.add_argument("--json", action="store_true", help="alias for --format json")
    ap.add_argument("--fail-if-alerts", action="store_true",
                    help="exit 1 when there is at least one alert (for cron/CI)")
    args = ap.parse_args()

    cfg: dict = {}
    if args.watch:
        cfg = load_watchlist(args.watch)
    watching = cfg.get("models", [])
    if args.all:
        watching = ["*"]
    watching = list(dict.fromkeys(watching + args.model))   # de-dupe, keep order
    if not watching:
        ap.error("nothing to watch: pass --watch, --model, or --all")

    alerts = select_alerts(
        load_log(args.log), watching,
        types=cfg.get("types"),
        min_price_change_pct=cfg.get("minPriceChangePct"),
    )

    out_format = "json" if args.json else args.format
    if out_format == "json":
        print(json.dumps({"watching": watching, "count": len(alerts), "alerts": alerts},
                         indent=2, ensure_ascii=False))
    elif out_format == "email":
        mail = build_email(alerts, watching)
        print(f"Subject: {mail['subject']}\n\n{mail['text']}\n\n--- html ---\n{mail['html']}")
    elif out_format == "slack":
        print(json.dumps(build_slack(alerts), indent=2, ensure_ascii=False))
    elif out_format == "webhook":
        print(json.dumps(build_webhook(alerts, watching), indent=2, ensure_ascii=False))
    else:
        if not alerts:
            print(f"No alerts for {len(watching)} watch target(s).")
        for a in alerts:
            print(f"[{a['severity'].upper():8}] {a['message']}  ({a['detected_at']})")
        print(f"\n{len(alerts)} alert(s).")

    return 1 if (alerts and args.fail_if_alerts) else 0


if __name__ == "__main__":
    sys.exit(main())
