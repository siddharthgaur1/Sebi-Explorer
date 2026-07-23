# Security

## Threat model

SEBI Explorer is a read-only analytics dashboard over a local SQLite snapshot of
**public** SEBI adjudication orders. It has no login, no user-supplied data path,
and no LLM. The only external interaction is the scraper (`scripts/scrape.py`),
run manually by the operator, never by a web request.

Assumed trusted: the operator, the committed seed database, the source.
Untrusted: the SEBI website's HTML (parsed by the scraper) and the search box.

## What is mitigated

| Risk | Status | Where |
|---|---|---|
| SQL injection | **Not applicable** — the app loads the table with pandas and filters in-memory; no user input is concatenated into SQL | `src/app.py` |
| Secrets in git history | **Clean** — `gitleaks`: 0 findings; no `.env` ever tracked; no keys anywhere (no LLM) |
| Dependency CVEs | **Clean** — `pip-audit`: no known vulnerabilities; versions pinned |
| Scraper hanging on a slow response | **Mitigated** — `requests` calls use `timeout=20` | `scripts/scrape.py` |
| Committed data | **Public record** — the seed DB holds SEBI's own published enforcement orders, each with its source URL; nothing private or fabricated |

## What is NOT mitigated / notes

- **No authentication.** It is a public, read-only dashboard; there is nothing to
  authenticate and nothing to write.
- **The scraper trusts SEBI's HTML structure.** If SEBI changes its markup the
  parser may extract wrong fields; this is a data-quality risk, not a security one.
  The scraper is never invoked from the web app.
- **The demo ships a small sample** (a few dozen real orders), not the full 11k
  corpus — enough to exercise every feature. Run `python scripts/scrape.py --all`
  to build the complete set locally.

## Reporting

Open an issue. Portfolio/demo project, no production deployment, no security SLA.
