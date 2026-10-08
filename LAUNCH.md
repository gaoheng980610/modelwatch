# Launch checklist

Everything below is a **human-identity step** — accounts, verification, DNS, payments. The code,
data and site are already built and verified; none of this needs a developer, and none of it needs
a code change.

Do them in order. **Steps 1–3 are the entire launch.** Steps 4–6 are later, optional, and only
matter once there is traffic.

---

## 0. Preconditions (already true)

```bash
python src/collector.py     # data is current
python src/validate.py      # shape is valid
python src/audit.py         # content is clean
python src/build_site.py    # site/ is regenerated
python src/check_links.py   # every internal link resolves
python -m unittest discover -s tests
```

All six pass. The first snapshot is already stored in `data/history/`, so the change feed starts
accruing from day one.

---

## 1. Repository — **first snapshot starts compounding here**

1. Create an empty GitHub repo named `modelwatch` (public — the data is meant to be seen).
2. Push this directory to it.
3. On the repo's **Actions** tab, confirm the `collect` workflow is enabled.

That is the whole step. From tomorrow onward, GitHub runs the collector daily at 06:17 UTC:
it tests, collects, validates, audits, builds, checks links, and commits the new snapshot.

> This step is why the change history becomes an asset. Until it runs, there is exactly one
> snapshot and the change feed is empty — correctly, and by design.

**Optional, when you want verified live data:** add a repository secret named
`ANTHROPIC_API_KEY`. Absent, the collector simply skips that adapter; nothing breaks.

---

## 2. Host the site — free tier is fine

**Cloudflare Pages** (recommended: free, global, reads the `_headers` file the build emits):

- Create a Pages project → *Connect to Git* → pick the repo.
- Build command: `python src/build_site.py`
- Build output directory: `site`
- Environment variable: `MODELWATCH_BASE_URL` = the address it will be served at (see step 3).

Netlify or Vercel work identically; both also honour `site/_headers`.

---

## 3. Point the domain

1. Buy a domain (any registrar; Cloudflare Registrar sells at cost).
2. Add it as a custom domain on the Pages project and follow the DNS instructions.
3. Set `MODELWATCH_BASE_URL` (step 2) to that origin, **with no trailing slash**, then redeploy.

That variable drives canonical URLs, Open Graph tags and `sitemap.xml` — getting it right is what
makes the programmatic pages indexable under the right host.

---

## 4. Verify (2 minutes)

- [ ] `https://<domain>/` loads, and the theme toggle sticks across a reload.
- [ ] `https://<domain>/api/v1/models.json` returns JSON.
- [ ] `https://<domain>/sitemap.xml` shows the correct host in every `<loc>`.
- [ ] `https://<domain>/robots.txt` points at that sitemap.
- [ ] A made-up URL (e.g. `/models/nope.html`) shows the branded 404 and its search box works.
- [ ] Lighthouse on the home page: Accessibility / Best Practices / SEO all 100.
- [ ] Submit `sitemap.xml` in Google Search Console.

---

## 5. Client packages (when you want distribution)

```bash
cd clients/js && npm publish          # needs an npm account + `npm login`
cd clients/py && python -m build && twine upload dist/*
```

Both are dependency-free and already read the public API.

---

## 6. Paid tiers (only once there is traffic)

Stripe account → a checkout link. The change feed (`/api/v1/changes.json`) is what the paid
Monitor wraps; the free tiers stay free.

---

## What is deliberately NOT here

No content farm, no scraped redistribution, no mass outbound. Every page is generated from sourced
data, and the merge rules in `src/adapters.py` are the reason the numbers can be trusted.
