# ModelWatch — full project record

Written 2026-10-08. Everything about this project in one place: what exists, what does not, what to
check, and how it could ever make money. The lessons that produced it are in `../LESSONS.md`.

---

## 1. Where it lives

| | |
|---|---|
| Repository | https://github.com/gaoheng980610/modelwatch (public) |
| Live site | https://gaoheng980610.github.io/modelwatch/ |
| Domain (pending) | modelwatch.is-a.dev — PR [#55587](https://github.com/is-a-dev/register/pull/55587), **open, awaiting a maintainer** |
| Automation | GitHub Actions, daily at 06:17 UTC **and on every push** |
| Cost to run | **$0.** No servers, no database, no domain fee. |

## 2. State, measured (not remembered)

```
models            372 across 52 providers
priced            370        tiered pricing  59
benchmarks        233        open weights   156
snapshots         10 and growing
change log        9 entries / 32 changes   ← it grew from 7/25 within one hour
site              751 pages
tests             63 (core) + 6 (py client) + 7 (js client)
repo              24 commits, 44 tracked files
```

## 3. How it runs, without anyone

Every push **and** every day at 06:17 UTC, GitHub Actions:

```
unit tests → collect → validate → audit → build → check internal links
           → check rendered figures → commit the data snapshot → deploy to Pages
```

Each run appends a snapshot and, if anything moved, an entry to the change log. **That is the only
part of this project whose value grows with time** — and it is the only part that cannot be
reconstructed retroactively. Everything else could be rebuilt from scratch in a day.

## 4. What is done

**Data** — 372 models with price (incl. **tiered pricing bands**, 59), context window, capabilities,
modalities, reasoning effort levels, knowledge cutoff, third-party benchmarks, open-weights repo id,
release date. Every figure carries a source URL, a confidence level and an `as_of` date. A
confidence-aware merge means a third-party source can never overwrite first-party data, and
disagreements are surfaced rather than hidden.

**Site** — index (filter/sort by name, provider, price, context, vision, open weights, intelligence),
`/new`, `/pricing`, `/leaderboard`, `/trends`, `/report`, `/docs`, `/compare` (any pair, client-side
+ 318 static pages), per-model pages, per-provider pages, `404`, Atom feed.

**APIs** — `/api/v1/models.json`, `/changes.json` (latest diff), `/history.json` (the full log).

**Clients** — dependency-free npm and PyPI packages, both tested against the live API.

**Verification** — 63 unit tests, plus five independent gates in CI: `validate` (shape), `audit`
(content — duplicates, dead rows, provenance), `check_links` (21.6k internal links + sitemap),
`check_claims` (recomputes the figures rendered on the page, **without importing the generator**, so
it cannot share a bug with it), and Lighthouse 100 (accessibility / best practices / SEO / agentic
browsing, light and dark, on every page type).

**Monetization groundwork** — an alert engine (`src/alerts.py`): watchlist in, alerts out, with
severity derived from the *direction* of a change. Payload renderers for email, Slack and webhook.
`--fail-if-alerts` for cron. Only *sending* is missing, and that is infrastructure.

## 5. What is NOT done — and what each one is blocked on

| Missing | Blocked on |
|---|---|
| Custom domain live | PR merge (human) + 2 clicks in repo Settings → Pages |
| Search engines told about the site | Search Console verification (human account) |
| **Anyone knowing it exists** | **Someone linking to it. Nothing else moves this.** |
| Alert *delivery* (email/webhook) | Infra + an account |
| Billing for a paid tier | Stripe (human account) |
| Any measurement of traffic | **No analytics at all — see §7** |

## 6. What to check, and when

**Daily (the automation does the work; this is only verification)**
- Actions ran green: https://github.com/gaoheng980610/modelwatch/actions
- The clock advanced: `/api/v1/history.json` → `meta.entries` should never go down.
- The site still serves: https://gaoheng980610.github.io/modelwatch/

**Weekly**
- Any failed runs in the last 7 days (a silently failing collector is the worst case — the log stops
  growing and nothing warns you).
- Anything notable in the log: large price moves, retirements, new model families.
- Indexing progress (once Search Console exists): how many pages Google has actually indexed.

**Monthly**
- **Is anyone visiting?** Currently unanswerable — §7.
- Are the numbers still right? Spot-check two or three models against the vendor's own page.
- Has the competitive picture changed? (artificialanalysis.ai and llm-prices.com are the two that
  matter; a browser check is enough.)

## 7. Known gap: we are blind

**There is no analytics of any kind.** We cannot tell whether zero or ten thousand people visit. For
a project whose entire remaining risk is discovery, that is the most important missing piece.

Options, cheapest first:
1. **Cloudflare Web Analytics** — free, no cookies, no consent banner. Point the site at Cloudflare,
   or use their JS snippet. *Needs an account.*
2. A self-hosted counter (Umami, Plausible CE) — needs a host.
3. GitHub Pages offers **no** traffic statistics. Do not count on it.

Until one of these exists, "check monthly: is anyone visiting?" has no answer, and any claim about
traction is a guess.

## 8. Monetization — the honest version

**First principle: with no visitors, every model below earns exactly zero.** Monetization is not the
current problem; discovery is. The order is forced.

**1. Affiliate / referral — the realistic first revenue.**
The site already ranks models and compares prices; that is precisely what referral programs pay for.
Add "try this model" links for providers and inference platforms that run affiliate programs
(OpenRouter and most clouds do). No product to build, no billing, no support, no gate except signing
up for the programs. Earns pennies per click and needs volume — but it is *the* standard revenue line
for a price-comparison site and it costs almost nothing to switch on.

**2. The paid change monitor — the better business, and the speculative one.**
"Tell me the moment a model I depend on changes price, limits, or gets retired." This is the only
thing here nobody else publishes: a dated change history. The engine is already built. Missing:
delivery, billing, and — most importantly — **evidence that anyone would pay.**
Honest sizing: a team burning real money on inference could save more than the subscription from one
price change. But that is a hypothesis, not a finding. Do not build the billing before someone asks
to pay.

**3. Data licensing / a paid API tier.** Needs a reputation first. Later, maybe.

**4. Sponsorship or ads.** Needs traffic we do not have. Later.

**5. Selling the site.** An exit, not a model — and it needs traffic to be worth anything.

**What I would NOT do:** build the paid tier before there is a single user. A subscription product
with no users costs support time and earns nothing, and it would repeat the original mistake of
building ahead of evidence.

## 9. The one thing that actually matters

Everything above is downstream of one question: **will anyone find this?**

It is reachable, indexable, fast, accurate, sourced and free — and none of that produces a single
visitor on its own. The remaining work is not engineering. It is: merge the domain PR, verify with a
search console, and get one person with an audience to link to it. Two of those need the account
holder; the third needs someone to care.
