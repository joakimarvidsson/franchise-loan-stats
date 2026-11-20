# Franchise Loan Stats

**https://franchiseloanstats.com/**

How SBA 7(a) loans to each franchise brand have actually performed: loans made, share charged off with
95% confidence intervals, outcomes by approval year, the lenders that finance each brand, and typical loan
size. Also by industry, lender and state. Free to use; the brand table is free to download.

Everything is computed by the code in this repository from two public-domain sources:

- [SBA 7(a) & 504 FOIA loan data](https://data.sba.gov/dataset/7a-504-foia) (7(a) files, quarterly)
- [SBA Franchise Directory](https://www.sba.gov/document/support-sba-franchise-directory)

This project is independent and is not affiliated with or endorsed by the U.S. Small Business Administration.

## How it works

1. `pipelines/` checks the SBA sources daily, and when one changes downloads the files, matches loans to
   brands, aggregates with DuckDB, validates, and writes `data/published/`.
2. `site/` (Astro) renders about 1,900 static pages from that output.
3. GitHub Actions tests, builds, deploys to GitHub Pages, smoke-tests production and notifies search engines.

Method, definitions and limits: https://franchiseloanstats.com/methodology/

## Run it yourself

```bash
pip install -r pipelines/requirements.txt pytest
python -m pipelines.run            # downloads ~900 MB into .cache/ and rebuilds data/published/
python -m pytest tests -q
cd site && npm ci && npm run build && npm run check:dist
```

## Corrections

Brand matching lives in [`pipelines/brand_aliases.csv`](pipelines/brand_aliases.csv). If two names are the
same franchise system, or two systems were wrongly joined, open an issue or email
franchiseloanstats@agentmail.to.

## Licence

Code: MIT. Derived data in `data/published/`: CC BY 4.0 (credit "Franchise Loan Stats" with a link).
Source data: U.S. Government works, public domain.
