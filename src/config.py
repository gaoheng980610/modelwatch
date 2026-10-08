"""One source of truth for the site's public origin.

The builder and the link checker MUST agree on this. If they disagree, the
checker either misses broken links or invents hundreds of them — which is
exactly what happened when each resolved the origin independently.

    MODELWATCH_CNAME     set it and the site moves to https://<cname> (and a
                         CNAME file is emitted for GitHub Pages). Takes priority.
    MODELWATCH_BASE_URL  any other origin, e.g. https://user.github.io/repo
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

CNAME = os.environ.get("MODELWATCH_CNAME", "").strip()

BASE_URL = (os.environ.get("MODELWATCH_BASE_URL", "").strip().rstrip("/")
            or (f"https://{CNAME}" if CNAME else "https://modelwatch.example"))

# A project page is served from a sub-path; every root-absolute link needs it.
BASE_PATH = urlsplit(BASE_URL).path.rstrip("/")

# Cloudflare Web Analytics token. Without analytics this project is blind: we
# cannot tell zero visitors from ten thousand, and discovery is its entire
# remaining risk. Set as a repo variable in CI; left empty it injects nothing.
CF_ANALYTICS = os.environ.get("MODELWATCH_CF_ANALYTICS", "").strip()
