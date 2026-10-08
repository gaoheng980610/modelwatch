# Operations — how to work on this in **this environment**

`PROJECT.md` says what the project is. This says how to operate it here, and what will look broken
when it isn't. Read this before touching anything in a fresh session.

---

## 1. Environment truths (this machine, checked 2026-10-08)

**The network blocks `github.com`, but not all of GitHub.**

| Host | Reachable | Notes |
|---|---|---|
| `github.com` | ❌ intermittently | `git push` / `git fetch` fail without the proxy |
| `api.github.com` | ✅ | GitHub REST API works directly — handy for state checks |
| `*.github.io` | ✅ | the live site |
| `openrouter.ai` | ✅ | the data source |

The browser (chrome-devtools MCP) reaches `github.com` fine — so the GitHub UI can be checked even
when git cannot reach it. That asymmetry is normal here and not a bug.

**A local proxy runs at `127.0.0.1:7897`.** Git is configured to use it, **repo-locally**:

```bash
git config --get http.proxy     # -> http://127.0.0.1:7897
```

If the proxy application is not running, git will fail with either
`Failed to connect to github.com port 443` or `OpenSSL SSL_connect: SSL_ERROR_SYSCALL`.
**Neither means the repository is broken.** Ask the human to start the proxy, or check whether it is
listening before debugging anything else.

**Credentials are cached** in Git Credential Manager, so `git push` does not prompt.

**`http.sslVerify=false` is set globally on this machine** (not by this project). HTTPS certificate
verification is therefore off for git everywhere on it. Worth fixing at some point; do not assume it
was deliberate.

---

## 2. The routine

```bash
cd /d/test/venture/modelwatch

# ALWAYS pull first. The CI commits a data snapshot on every run, so the remote
# is usually ahead, and data/*.json conflicts are normal — both sides are
# generated files and either is valid. -X ours keeps local and moves on.
git pull --no-edit -X ours

python src/collector.py      # fetch, merge, write models.json + a snapshot + maybe a log entry
python src/validate.py       # shape
python src/audit.py          # content: duplicates, dead rows, provenance
python src/build_site.py     # regenerate site/
python src/check_links.py    # 21k+ internal links + every sitemap URL
python src/check_claims.py   # recomputes the figures rendered on the page
python -m unittest discover -s tests

git add -A && git commit -m "…" && git push
```

Writing data files by hand is a mistake. Everything under `data/` is generated.

---

## 3. Configuration that lives outside the code

| Setting | Where | Value |
|---|---|---|
| Pages source | repo Settings → Pages | **GitHub Actions** (must stay) |
| Custom domain | repo Settings → Pages | `modelwatch.is-a.dev` — **pending PR merge** |
| `MODELWATCH_CF_ANALYTICS` | workflow default; optional repo variable overrides | Cloudflare token, not a secret |
| `MODELWATCH_CNAME` | repo variable, optional | wins over `MODELWATCH_BASE_URL` if set |
| `MODELWATCH_BASE_URL` | workflow `env:` | `https://gaoheng980610.github.io/modelwatch` |

`src/config.py` is the single source of truth for the origin. **`build_site.py` and `check_links.py`
both import it on purpose** — when they each resolved the origin independently, the checker invented
803 phantom broken links.

---

## 4. What failure looks like

| Symptom | Meaning |
|---|---|
| `git push` → `Failed to connect … port 443` / `SSL_ERROR_SYSCALL` | the proxy is off. Not a repo problem. |
| `git push` → `Updates were rejected … remote contains work` | the CI committed. `git pull --no-edit -X ours`, then push. |
| `check_links` reports hundreds of broken links | an origin/prefix mismatch — check §3 and `src/config.py`. |
| `check_claims` reports a MISMATCH | a rendered figure disagrees with `data/models.json`. **Trust it.** |
| Actions run red at `deploy` only | Pages settings, not the data pipeline. The collect job still succeeded. |
| The change log stops growing | the worst case: the collector is silently failing. Check Actions. |

**The last one is the one that matters.** A site that stops updating does not announce itself.

---

## 5. Verifying a change actually landed

Do not trust the build output — check the deployed artefact:

- HTML: load the live URL and inspect the DOM, or read `/api/v1/history.json` and watch
  `meta.entries` increase.
- Analytics: the beacon must actually POST. `list_network_requests` should show
  `POST https://cloudflareinsights.com/cdn-cgi/rum → 204`.
- Anything the CI does: read the run on the Actions page, not the local build.

This project has repeatedly paid for the difference between "the build said OK" and "the live page
does the thing".

---

## 6. Do not

- **Add features.** See `../LESSONS.md`. The build phase is over; more features are negative value
  until someone uses it.
- Hand-edit `data/`.
- Serve the site from the repo root — everything lives under `site/`, and paths assume the
  configuration in §3.
- Assume a green local build means a green deployment.
