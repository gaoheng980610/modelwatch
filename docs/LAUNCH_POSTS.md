# Launch material

Drafts, ready to post the moment the site is live (see `LAUNCH.md` for the go-live steps).

**The rule for all of it: lead with the data, not the product.** A developer audience punishes
marketing and rewards a finding. Every claim below is already on the site, sourced.

---

## Positioning, in one line

> An index of AI models — price, context window, capabilities, benchmarks — where every number
> carries its source and the date it was true.

---

## Show HN

**Title options** (HN rewards plain and specific):

1. `Show HN: An index of 372 AI models, with a source cited for every number`
2. `Show HN: I indexed AI model prices and context windows, and dated every figure`
3. `Show HN: AI model prices, context windows and benchmarks in one queryable index`

**Body:**

> I kept needing the same three facts about a model — what it costs, how much context it takes, and
> whether it's still current — and kept finding pages that listed one of them without saying when it
> was last true. So I built the index I wanted: 372 models across 52 providers, where every figure
> carries a source URL and an `as_of` date.
>
> Three things fell out of the data while assembling it:
>
> - **Context windows grew ~122× in three years.** Median by release year: 8K (2023) → 128K (2024) →
>   200K (2025) → 1M (2026).
> - **Multimodal stopped being a feature.** Share of each year's models accepting image input: 0% →
>   27% → 53% → 71%.
> - **Prices did not fall.** The median input price has stayed in a narrow band ($0.30–$0.65/MTok)
>   the whole time. What changed is what that buys you.
>
> It's a static site plus a JSON API, no signup, no tracking. You can filter to "1M+ context, vision,
> under $1" and sort by benchmark score.
>
> Honest about the data: 9 of the 372 records are backed by first-party vendor documentation; the
> other 363 come from a public aggregator and are labelled as third-party. A third-party source can
> never overwrite a first-party figure, and records where sources disagree say so on the page. I
> don't run any benchmarks — those are third-party scores, kept in their own field.
>
> <https://example.com> — the analysis is at `/report.html`, and the raw JSON is at
> `/api/v1/models.json` if you want to check any of the arithmetic.

---

## Technical communities (r/LocalLLaMA, Discord, lobste.rs)

Shorter, and skip the "Show HN" framing:

> I built a sourced index of 372 models — price per MTok, context window, modalities, release date,
> and third-party benchmark scores where they exist. Every record links its source and states the
> date it was true.
>
> The one view I use most is "cheapest model that still clears a capability bar" — there's a
> leaderboard ranked by intelligence index with the **input price per index point** in the last
> column. Sonnet 5.5 works out at $0.036/point; Fable 5.1 at $0.187. Same ballpark of capability,
> 5× the cost per point.
>
> No signup. JSON API: `/api/v1/models.json`.

---

## Directory / newsletter blurb (≤ 50 words)

> **ModelWatch** — a sourced index of AI models: price per million tokens, context window,
> capabilities, release dates and third-party benchmarks. Every figure cites its source and the date
> it was true, so a stale number is visibly stale. Free JSON API, no signup.

---

## Objections, answered honestly

Prepare for these; they are all fair.

**"Isn't this just an aggregator's data?"**
Partly, yes — and the site says so on every record. About two thirds of records are third-party;
the rest is vendor documentation. The work is not the fetching, it's the provenance, the merge rules
(a third-party source can never overwrite a first-party one), and the dated change history that
accrues daily and cannot be reconstructed after the fact.

**"Why should I trust your numbers?"**
You shouldn't, on our word. Every number links to its source, and the page states how old it is.
That's the entire design premise.

**"How does this make money?"**
It doesn't yet. The API and the site stay free. A paid tier that alerts you when a model you depend
on changes price, limits, or gets retired is planned — that's the one thing here that is genuinely
perishable, and the only thing worth charging for.

**"Another LLM pricing site?"**
Most list today's prices with no date and no source, which makes them unusable for the question
"is this still true?". Here `as_of` is a first-class field, and the change log is public.

**"Your data is wrong about X."**
Genuinely useful — please say which model and what the correct figure is with a source. Corrections
go into the same pipeline as everything else.

---

## What NOT to do

Distribution here is honest or it is worthless, because the product's only real asset is
trustworthiness:

- **No asking for upvotes.** It's against every platform's rules and it poisons the well.
- **No cross-posting the same text to six subreddits in an hour.** One community at a time; answer
  in the comments rather than blasting links.
- **No astroturfed comments**, no sockpuppets, no fake "just found this" posts.
- **No unsolicited DMs** to people who never asked.
- **Don't hide the aggregator.** If someone asks where the data comes from, the answer is on the
  page already. Getting caught overstating provenance would end the project's credibility, which is
  the only thing it has.
