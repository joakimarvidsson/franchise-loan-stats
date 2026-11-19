# Franchise Loan Stats — engineering guide

Public site: https://joakimarvidsson.github.io/franchise-loan-stats/
This repository is public. Business strategy, partner contacts, financials and the task queue live in the
private control repository `joakimarvidsson/freehold`. Never commit anything from there to this repo.

## What this is

A static site that reports how SBA 7(a) loans to each franchise brand performed, computed from two
public-domain SBA files. One deterministic pipeline produces JSON; Astro renders pages from that JSON.

```
pipelines/        Python + DuckDB. sources -> brands (entity resolution) -> aggregate -> validate -> publish
  brand_aliases.csv   hand-reviewed brand merges, renames and "keep separate" rows
data/published/   the only input the site reads (brands, industries, lenders, states, summary, manifest, csv)
data/history/     one compact snapshot per SBA data date, for change detection
data/changes/     differences between consecutive snapshots
site/             Astro 7 static site (TypeScript). No client framework; small inline scripts only
scripts/          smoke.mjs (production check), indexnow.mjs (search-engine ping)
tests/            pytest for the pipeline; site/tests for vitest
state/            pipeline_runs.jsonl, an append-only run log
partners.json     commercial placements; only status "live" with a url is ever rendered
.github/workflows ci, deploy (build -> Pages -> smoke -> IndexNow), refresh (daily source check), health (6-hourly)
```

## Commands

```
pip install -r pipelines/requirements.txt pytest
python -m pytest tests -q                    # pipeline tests (also validates the committed snapshot)
python -m pipelines.run --check              # are the SBA sources newer than the snapshot?
python -m pipelines.run                      # refresh if changed (downloads ~900 MB to .cache/)
FLS_CACHE=/path python -m pipelines.run --offline   # rebuild from already-downloaded files
cd site && npm ci && npm test && npm run build && npm run check:dist
node scripts/smoke.mjs                       # checks production serves this checkout's data
```

## Rules that are not negotiable

1. **Figures come only from `data/published/`.** Never type a statistic into a page, component or test
   expectation for real brands. Explanatory text may be written by hand; numbers may not.
2. **Never weaken a validation gate to get a build out.** If `validate.py` rejects a build, find out why.
   A deliberate methodology change is published with `--allow-shift`, and the commit message says what
   changed and why.
3. **No borrower-level data.** The SBA file names borrowers. Only aggregates leave `aggregate.py`.
   `tests/test_pipeline.py` checks this; keep that test.
4. **Small samples.** No rate below 10 seasoned loans. No rank below 30. Do not add copy that calls a brand
   better or worse than a benchmark unless the confidence intervals do not overlap (`compareRates`).
5. **Wording.** Say "charge-off rate of SBA loans". Do not say "failure rate", "risky franchise", "worst
   franchise", "safe" or anything that rates a business. Report the record and its limits.
6. **Brand merges are evidence-based.** A merge needs an exact normalised-name match, the generic-descriptor
   rule, or a reviewed row in `brand_aliases.csv` with a note. Never merge on similarity alone. When unsure,
   keep separate. Wrong merges found later get an empty-target row ("kept separate").
7. **Commercial links.** A link is an affiliate or sponsor link only when the programme is approved and its
   entry in `partners.json` is `live`. No placeholders, no "coming soon" offers, no undisclosed placements.
   Every placement carries its label and `rel="sponsored"`.
8. **The site is independent of the SBA.** Keep the non-affiliation statement in the footer and methodology.

## Conventions

- Python 3.12, type hints, no pandas in the pipeline (DuckDB SQL plus plain Python).
- Astro pages: one `<h1>`, unique title and description, breadcrumbs via the `crumbs` prop, internal links
  through `url()` from `src/lib/site.ts` (the site is served under a base path until it has its own domain).
- `npm run check:dist` must pass: it fails on duplicate titles or descriptions, broken internal links,
  missing canonicals, rendered `undefined`/`NaN`, or fewer than 1,500 pages.
- Work on a branch and open a pull request for anything beyond data refreshes and alias rows; CI must be
  green before merging. Commit messages: `data:`, `site:`, `pipeline:`, `ops:`, `docs:` prefixes.
- Moving to a custom domain: set `SITE_URL` and `BASE_PATH=/` in the deploy workflow and update
  `scripts/smoke.mjs`'s default. Nothing else hard-codes the address.

## When something breaks

- Refresh failed: the previous snapshot stays live by design. Read the last line of
  `state/pipeline_runs.jsonl` and the workflow log. Source page layout changes are the usual cause: fix
  `pipelines/sources.py`, add a test, re-run the `Refresh data` workflow.
- Deploy failed after merge: revert the merge commit first, then investigate.
- Health check issue open (`outage` label): run `node scripts/smoke.mjs` locally to see which check fails.
- Two retries at most for any failing job, then record it in the control repository's incident log and stop.
