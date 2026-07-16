# SEBI Enforcement Explorer

[![CI](https://github.com/siddharthgaur1/sebi-explorer/actions/workflows/ci.yml/badge.svg)](https://github.com/siddharthgaur1/sebi-explorer/actions/workflows/ci.yml) [![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

SEBI (India's securities regulator) publishes thousands of enforcement
orders on its website, but as an unstructured HTML table with no search, no
filtering, and no way to see patterns across it. This scrapes the public
listing, classifies each order by violation type, extracts the named entity
and penalty amount from the title, and puts it in a searchable dashboard —
turning a stack of individually-readable PDFs into something a compliance
analyst or researcher can actually query.

## Architecture

```
scripts/scrape.py
   ├── fetches sebi.gov.in listing pages (1.2s crawl delay, polite UA)
   ├── classify()        regex → 13 violation categories
   ├── extract_entity()  best-effort NER from the order title
   └── SQLite storage (data/sebi_orders.db), URL-deduped on re-run

                    │
                    ▼
src/app.py (Streamlit)
   ├── extract_penalty_cr()   regex-extracts ₹ amounts from titles
   ├── Overview / Timeline Heatmap / Penalties / Entity Network / Orders Table
   └── Entity co-occurrence graph (NetworkX): entities linked when they
       share a violation type + year
```

## Setup

```bash
pip install -r requirements.txt
python scripts/scrape.py              # fetch latest ~200 orders
python scripts/scrape.py --pages 20   # fetch ~500
python scripts/scrape.py --all        # fetch everything (~11k orders, ~20 min)
```

## Running it

```bash
streamlit run src/app.py
pytest tests/ -v
```

`scripts/scrape.py`'s parsing/classification logic and `src/app.py`'s
penalty extraction are unit-tested against static HTML fixtures — the test
suite never hits sebi.gov.in.

## Design decisions

**1.2s crawl delay and a real User-Agent, not maximum-throughput
scraping.** This is a public regulator's website serving public disclosure
data — there's no reason to hammer it. The delay and session reuse (one
connection, not one per request) keep the scraper's footprint small and
polite regardless of how large `--all` runs.

**Regex classification and entity extraction, not an LLM.** 11k+ order
titles follow a small number of recurring phrasings ("in the matter of X",
"order against Y"). A dozen regex patterns cover the common cases at zero
marginal cost per order and are fully deterministic — worth it before
reaching for an LLM call per title, which would be slower, costlier, and
non-reproducible for what's fundamentally pattern matching on fairly
formulaic government-document titles.

**"Best-effort" is stated explicitly in the UI, not hidden.** Entity and
penalty extraction both regularly fail (return `""` / `None`) on titles that
don't match the known patterns — the Penalties tab explicitly tells the
user when penalty extraction found nothing, rather than silently showing
an empty chart with no explanation.

## Bugs found and fixed during polish

- **`display.columns_map = {...}`** set an arbitrary attribute on a pandas
  DataFrame instead of using a local variable — clearly an accidental
  `display.` prefix (pandas allows this but warns; the intent was obviously
  a plain dict). Fixed to a local variable.
- **No tests existed**, so `scrape.py`'s HTML parsing and `app.py`'s
  penalty-amount regex had never been exercised against edge cases (relative
  vs. absolute URLs, lakh-vs-crore conversion, unmatched titles). Added
  `tests/` with fixtures instead of live requests.

## What I'd improve with more time

1. **Entity extraction and penalty extraction are both regex, both
   "best-effort."** A real evaluation set (manually labeled entity/penalty
   ground truth for a sample of orders) would turn "best-effort" into a
   measured precision/recall number, and make it possible to compare regex
   against an LLM-based extractor on cost/accuracy tradeoffs rather than
   guessing.
2. **No incremental re-classification.** If a violation-type pattern is
   added or fixed, existing rows in the DB keep their old classification
   until a full re-scrape. A `reclassify.py` script re-running `classify()`
   over existing rows would be a small, useful addition.
3. **Entity network doesn't dedupe near-identical entity strings** (e.g.
   "ABC Ltd" vs. "ABC Limited" from different title phrasings) — they'd show
   as separate nodes. Fuzzy-matching entity names before building the graph
   would make the co-occurrence network meaningfully more accurate.

## Related projects

- [llm-regression-detector](https://github.com/siddharthgaur1/llm-regression-detector) — CI/CD regression detection for an LLM classifier's eval suite.
- [rag-hybrid-search](https://github.com/siddharthgaur1/rag-hybrid-search) — hybrid dense+BM25 RAG pipeline.
- [finrag](https://github.com/siddharthgaur1/finrag) — hybrid RAG over financial PDFs.
- [querypilot](https://github.com/siddharthgaur1/querypilot) — natural language to SQL agent.
- [rail-graph](https://github.com/siddharthgaur1/rail-graph) — graph-theoretic analysis of a railway network.
- [ipo-gmp](https://github.com/siddharthgaur1/ipo-gmp) — XGBoost IPO listing-return predictor.
