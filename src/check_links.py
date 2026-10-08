#!/usr/bin/env python3
"""Check that every internal link and asset in the generated site resolves.

The site is ~750 programmatically-generated pages; a wrong slug silently becomes
a 404 for a reader (and a crawl error for a search engine). This walks the built
output, resolves every href/src, and also verifies that every URL advertised in
sitemap.xml actually exists.

Stdlib only.  Exit 1 if anything is broken.

    python src/check_links.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
BASE_URL = os.environ.get("MODELWATCH_BASE_URL", "https://modelwatch.example").rstrip("/")

ATTR = re.compile(r'(?:href|src)="([^"]+)"')
LOC = re.compile(r"<loc>([^<]+)</loc>")
# Script bodies are not markup. Without this, a page that builds links in JS
# (e.g. href="/models/'+id+'") is reported as a broken link.
SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)


def is_external(url: str) -> bool:
    return (not url) or url.startswith(("http://", "https://", "mailto:", "data:", "//", "#"))


def resolve(base_dir: Path, url: str) -> Path | None:
    """Map a site link to the file it should hit."""
    path = urlsplit(url).path
    if not path:
        return None
    target = SITE / path.lstrip("/") if path.startswith("/") else (base_dir / path)
    if target.is_dir():
        target = target / "index.html"
    return target


def main() -> int:
    if not SITE.exists():
        print("no site/ — run src/build_site.py first")
        return 1

    pages = sorted(SITE.rglob("*.html"))
    broken: list[tuple[str, str]] = []
    checked = 0

    # Scan feed.xml too: its links are absolute against BASE_URL, and a broken
    # entry link is invisible in every reader that swallows it.
    targets = [(p, SCRIPT.sub("", p.read_text(encoding="utf-8"))) for p in pages]
    feed = SITE / "feed.xml"
    if feed.exists():
        targets.append((feed, feed.read_text(encoding="utf-8")))

    for page, text in targets:
        base_dir = page.parent
        for raw in ATTR.findall(text):
            url = raw[len(BASE_URL):] or "/" if raw.startswith(BASE_URL) else raw
            if is_external(url):
                continue
            checked += 1
            target = resolve(base_dir, url)
            if target is not None and not target.exists():
                broken.append((page.relative_to(SITE).as_posix(), raw))

    # sitemap.xml must only advertise pages that exist
    sitemap_broken = []
    sitemap = SITE / "sitemap.xml"
    if sitemap.exists():
        for loc in LOC.findall(sitemap.read_text(encoding="utf-8")):
            rel = loc[len(BASE_URL):].lstrip("/") if loc.startswith(BASE_URL) else loc
            target = SITE / rel if rel else SITE / "index.html"
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                sitemap_broken.append(loc)

    print(f"pages          {len(pages)}")
    print(f"links checked  {checked}")
    print(f"sitemap URLs   {len(LOC.findall(sitemap.read_text(encoding='utf-8'))) if sitemap.exists() else 0}")

    for src, url in broken[:25]:
        print(f"BROKEN  {src}  ->  {url}")
    for loc in sitemap_broken[:10]:
        print(f"BROKEN (sitemap)  {loc}")

    if broken or sitemap_broken:
        print(f"\nFAIL — {len(broken)} broken link(s), {len(sitemap_broken)} broken sitemap entrie(s)")
        return 1
    print("\nOK — every internal link and sitemap URL resolves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
