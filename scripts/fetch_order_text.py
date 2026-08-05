"""Fetch the full text of SEBI enforcement orders.

`scrape.py` collects listing *metadata* only — date, title, entity, URL. It
never downloads the order itself, so the database has no document text in it.
Anything that needs the actual content (fine-tuning, extraction, RAG over the
orders) is blocked until this has run.

Each order page links to a PDF; this follows that link, extracts the text, and
stores it in an `order_text` table keyed to `orders.id`.

    python scripts/fetch_order_text.py --limit 5      # try a handful first
    python scripts/fetch_order_text.py --all          # the full backlog

Resumable: already-fetched orders are skipped, and failures are recorded with
their reason rather than retried forever, so a long run can be interrupted and
restarted without losing progress or re-hammering documents that will never
parse.

Politeness: sebi.gov.in/robots.txt disallows only /js and /css, so these
documents are fetchable, but they are a public regulator's servers — the delay
below is deliberate and there is no concurrency. Do not "speed this up".

REPOSITORY SIZE WARNING: data/sebi_orders.db is committed as a small seed
snapshot (see the exception in .gitignore). Order text is roughly 74KB per
document, so a full backlog run produces a multi-hundred-megabyte database.
Do not commit it. Either point --db at a path outside the repo, or drop the
`!data/sebi_orders.db` exception before running at scale.
"""

import argparse
import hashlib
import io
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sebi_orders.db"
BASE_URL = "https://www.sebi.gov.in"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; sebi-explorer research scraper)"}
DELAY_S = 1.5
MIN_USEFUL_CHARS = 500


def init_text_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS order_text (
            order_id    INTEGER PRIMARY KEY REFERENCES orders(id),
            pdf_url     TEXT,
            text        TEXT,
            n_chars     INTEGER,
            n_pages     INTEGER,
            sha256      TEXT,
            status      TEXT NOT NULL,   -- ok | no_pdf_link | http_error | parse_error | too_short
            error       TEXT,
            fetched_at  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_order_text_status ON order_text(status);
    """)
    conn.commit()


def find_pdf_url(html: str) -> str | None:
    """Locate the order PDF on an order page.

    Most pages do NOT link the PDF with an anchor — they embed SEBI's viewer:

        <iframe src='https://www.sebi.gov.in/web/?file=https://.../ORDER_123.pdf'>

    so the anchor scan alone finds nothing. Checked in order of specificity;
    the bare-URL fallback is last because it would also match an unrelated PDF
    linked elsewhere in the page chrome.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1. The embedded viewer, which is the normal case.
    for iframe in soup.find_all("iframe", src=True):
        m = re.search(r"[?&]file=(?P<url>[^&'\"]+\.pdf)", iframe["src"], re.IGNORECASE)
        if m:
            return unquote(m.group("url"))

    # 2. A direct anchor to the document.
    for a in soup.find_all("a", href=True):
        if a["href"].lower().endswith(".pdf"):
            href = a["href"]
            return href if href.startswith("http") else BASE_URL + href

    # 3. Anything under the attachments path, absolute or relative.
    m = re.search(r'["\'](?P<url>(?:https?://[^"\']+)?/sebi_data/[^"\']+\.pdf)["\']', html, re.IGNORECASE)
    if m:
        url = m.group("url")
        return url if url.startswith("http") else BASE_URL + url
    return None


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages]
    return "\n\n".join(pages).strip(), len(pages)


def fetch_one(session: requests.Session, order_url: str) -> dict:
    result = {
        "pdf_url": None, "text": None, "n_chars": 0, "n_pages": 0,
        "sha256": None, "status": "ok", "error": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        page = session.get(order_url, timeout=30)
        page.raise_for_status()
    except Exception as e:  # noqa: BLE001 - one bad document must not abort a multi-hour run
        return {**result, "status": "http_error", "error": f"order page: {e}"}

    pdf_url = find_pdf_url(page.text)
    if not pdf_url:
        return {**result, "status": "no_pdf_link", "error": "no .pdf link on the order page"}
    result["pdf_url"] = pdf_url

    time.sleep(DELAY_S)
    try:
        pdf = session.get(pdf_url, timeout=60)
        pdf.raise_for_status()
    except Exception as e:  # noqa: BLE001 - recorded and skipped, not fatal
        return {**result, "status": "http_error", "error": f"pdf: {e}"}

    try:
        text, n_pages = extract_pdf_text(pdf.content)
    except Exception as e:  # noqa: BLE001 - pdfplumber raises a wide variety on malformed PDFs
        return {**result, "status": "parse_error", "error": f"{type(e).__name__}: {e}"}

    result.update(
        text=text, n_chars=len(text), n_pages=n_pages,
        sha256=hashlib.sha256(pdf.content).hexdigest(),
    )
    if len(text) < MIN_USEFUL_CHARS:
        # Almost always a scanned order with no text layer. Recorded rather
        # than dropped: "how much of the corpus is images" is a number the
        # dataset card has to state.
        result["status"] = "too_short"
        result["error"] = f"{len(text)} chars extracted; likely a scanned PDF needing OCR"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help="Database path. Point this outside the repo for a full run — "
                             "the committed seed DB must stay small.")
    parser.add_argument("--limit", type=int, default=10, help="Orders to fetch this run.")
    parser.add_argument("--all", action="store_true", help="Fetch every order lacking text.")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Retry every order not already recorded 'ok'. Needed after "
                             "fixing the PDF-locating logic, since old rows would "
                             "otherwise stay permanently skipped.")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"No database at {args.db}. Run scripts/scrape.py first.", file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.db)
    init_text_table(conn)

    # Without --retry-failed, anything already attempted is left alone so a long
    # run is not spent re-fetching documents that will never parse.
    skip = "('ok')" if args.retry_failed else \
           "('ok','no_pdf_link','parse_error','too_short','http_error')"
    query = f"""
        SELECT o.id, o.url FROM orders o
        LEFT JOIN order_text t ON t.order_id = o.id
        WHERE t.order_id IS NULL OR t.status NOT IN {skip}
        ORDER BY o.id
    """
    pending = conn.execute(query).fetchall()
    if not args.all:
        pending = pending[: args.limit]

    total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM order_text WHERE status='ok'").fetchone()[0]
    print(f"orders: {total} | with text: {done} | fetching now: {len(pending)}")
    if not pending:
        return 0

    session = requests.Session()
    session.headers.update(HEADERS)
    counts: dict[str, int] = {}

    for i, (order_id, order_url) in enumerate(pending, 1):
        result = fetch_one(session, order_url)
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        conn.execute(
            """INSERT INTO order_text
               (order_id, pdf_url, text, n_chars, n_pages, sha256, status, error, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(order_id) DO UPDATE SET
                 pdf_url=excluded.pdf_url, text=excluded.text, n_chars=excluded.n_chars,
                 n_pages=excluded.n_pages, sha256=excluded.sha256, status=excluded.status,
                 error=excluded.error, fetched_at=excluded.fetched_at""",
            (order_id, result["pdf_url"], result["text"], result["n_chars"],
             result["n_pages"], result["sha256"], result["status"], result["error"],
             result["fetched_at"]),
        )
        conn.commit()  # per-order, so an interrupted run keeps everything before it
        print(f"  [{i}/{len(pending)}] id={order_id} {result['status']} "
              f"{result['n_chars']} chars, {result['n_pages']}p"
              + (f" — {result['error']}" if result["error"] else ""))
        time.sleep(DELAY_S)

    print("\nthis run:", dict(sorted(counts.items())))
    ok = conn.execute("SELECT COUNT(*) FROM order_text WHERE status='ok'").fetchone()[0]
    print(f"orders with usable text: {ok}/{total}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
