# Moving to modelwatch.is-a.dev

Why: the site is live at `https://gaoheng980610.github.io/modelwatch/`, which works but reads as
"a repo under someone's username". A custom domain is the difference between a project and a
product. A real domain costs money; **is-a.dev gives a subdomain for free**, in exchange for
pointing it at a GitHub Pages site and keeping it real.

Trade-off, recorded honestly: **this domain is not ours.** The subdomain belongs to is-a.dev — if
the service ever shuts down, the URL dies with it, and it cannot be sold or moved. It is the right
call at zero budget and the wrong call as a permanent home. A registered domain (~¥70/year) is the
only version that is actually an asset.

## Format (checked against docs.is-a.dev on 2026-10-08, not recalled)

Copied verbatim from their GitHub Pages guide:

```json
{
    "owner": {
        "username": "github-username",
        "email": "me@example.com"
    },
    "records": {
        "CNAME": "github-username.github.io"
    }
}
```

Submitted as a new file `domains/modelwatch.json` in `is-a-dev/register`, via pull request.

## The file to submit

`domains/modelwatch.json`:

```json
{
    "owner": {
        "username": "gaoheng980610",
        "email": "gaoheng980610@users.noreply.github.com"
    },
    "records": {
        "CNAME": "gaoheng980610.github.io"
    }
}
```

The email is the GitHub *noreply* address on purpose: it routes to the account holder without
publishing a personal address, and it is a real deliverable address if a maintainer needs to make
contact.

## Sequence

1. **Human** opens the pull request (needs the account; see LAUNCH.md).
2. Maintainers merge it — typically 1–3 days.
3. **Human**, only after the merge: repo Settings → Pages → Custom Domain →
   `modelwatch.is-a.dev`, then tick *Enforce HTTPS*.
4. **Agent**: set `MODELWATCH_CNAME: modelwatch.is-a.dev` in the workflow (a commit, no human
   needed), which switches canonical URLs, the sitemap and every internal link, and emits the
   `CNAME` file Pages needs.
5. **Agent** verifies: the live URL serves, canonical/sitemap point at the new host, and
   `check_links.py` passes against it.

## Availability

Checked `domains/modelwatch.json` in `is-a-dev/register` via the GitHub API on 2026-10-08:
`404 Not Found` — no such file, so the name is free. Re-check before submitting; a pending PR can
exist without a merged file.
