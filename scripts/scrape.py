"""
SEBI Enforcement Orders Scraper
Fetches Adjudication Orders (AO) from sebi.gov.in, parses metadata
from titles, and stores everything in SQLite.

Usage:
    python scripts/scrape.py              # fetch latest 200 orders
    python scripts/scrape.py --pages 20   # fetch ~500 orders (25 per page)
    python scripts/scrape.py --all        # fetch everything (11k+ orders, takes time)
"""

import argparse
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DB_PATH   = Path(__file__).resolve().parent.parent / "data" / "sebi_orders.db"
BASE_URL  = "https://www.sebi.gov.in"
LIST_URL  = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=2&ssid=9&smid=6"
HEADERS   = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DELAY_S   = 1.2   # polite crawl delay

# ── Violation-type classifier ─────────────────────────────────────
VIOLATION_PATTERNS = [
    (r"insider.trad",                          "Insider Trading"),
    (r"illiquid.stock.option",                 "Illiquid Stock Options"),
    (r"front.runn",                            "Front Running"),
    (r"manipulat",                             "Market Manipulation"),
    (r"fraudulent|mislead|misrepresent",       "Fraud / Misrepresentation"),
    (r"takeover",                              "Takeover Code"),
    (r"disclosure|non.disclosure|sast",        "Disclosure Violation"),
    (r"investment.advi|research.anal",         "Unregistered Advisory"),
    (r"portfolio.manag",                       "Portfolio Manager"),
    (r"mutual.fund",                           "Mutual Fund"),
    (r"demat|depository",                      "Depository"),
    (r"broker|sub.broker|trading.memb",        "Broker / Sub-broker"),
    (r"settlement",                            "Settlement"),
]

def classify(title: str) -> str:
    t = title.lower()
    for pattern, label in VIOLATION_PATTERNS:
        if re.search(pattern, t):
            return label
    return "Other"


# ── Entity extractor ─────────────────────────────────────────────
def extract_entity(title: str) -> str:
    """Best-effort: extract the named entity from the order title."""
    patterns = [
        r"(?:in respect of|against|of)\s+([^\.–\-\|]{3,60}?)(?:\s+in the matter|\s+under|\.|$)",
        r"matter of\s+([^\.–\-\|]{3,60}?)(?:\s+[-–]|\.|$)",
        r"^(?:adjudication order|order)[^:]*?:\s*(.+?)(?:\s+in\b|\.|$)",
    ]
    for pat in patterns:
        m = re.search(pat, title, re.IGNORECASE)
        if m:
            entity = m.group(1).strip().strip("–-").strip()
            if 3 < len(entity) < 80:
                return entity
    return ""


# ── DB setup ─────────────────────────────────────────────────────
def init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            order_date    TEXT,
            year          INTEGER,
            month         TEXT,
            title         TEXT NOT NULL,
            entity        TEXT,
            violation_type TEXT,
            url           TEXT UNIQUE NOT NULL,
            scraped_at    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_year   ON orders(year);
        CREATE INDEX IF NOT EXISTS idx_vtype  ON orders(violation_type);
        CREATE INDEX IF NOT EXISTS idx_entity ON orders(entity);
    """)
    return conn


# ── Page parser ──────────────────────────────────────────────────
def parse_listing_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        date_text = cells[0].get_text(strip=True)
        link_tag  = cells[1].find("a")
        if not link_tag:
            continue
        title = link_tag.get_text(" ", strip=True)
        href  = link_tag.get("href", "")
        url   = href if href.startswith("http") else BASE_URL + href

        # parse date
        order_date, year, month = None, None, ""
        try:
            dt = datetime.strptime(date_text, "%b %d, %Y")
            order_date = dt.date().isoformat()
            year       = dt.year
            month      = dt.strftime("%B")
        except ValueError:
            pass

        rows.append({
            "order_date":     order_date,
            "year":           year,
            "month":          month,
            "title":          title,
            "entity":         extract_entity(title),
            "violation_type": classify(title),
            "url":            url,
            "scraped_at":     datetime.utcnow().isoformat(),
        })
    return rows


def get_next_url(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    next_link = soup.find("a", string=lambda t: t and "Next" in t)
    if next_link:
        js = next_link.get("href", "")
        m = re.search(r"searchFormNewsList\('n',\s*'(\d+)'\)", js)
        if m:
            return LIST_URL + f"&searchText=&fromDate=&toDate=&department=&subSection=6&subSubSection=6&pageNum={m.group(1)}"
    return None


# ── Main scrape loop ─────────────────────────────────────────────
def scrape(max_pages: int = 8):
    conn = init_db()
    existing = {r[0] for r in conn.execute("SELECT url FROM orders")}
    print(f"Existing records: {len(existing)}")

    session = requests.Session()
    session.headers.update(HEADERS)

    url = LIST_URL
    page_num = 0
    total_new = 0

    while url and page_num < max_pages:
        print(f"  Page {page_num + 1} / {max_pages} ...", end=" ", flush=True)
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            print(f"FAILED: {e}")
            break

        rows = parse_listing_page(resp.text)
        new_rows = [r for r in rows if r["url"] not in existing]
        print(f"{len(rows)} orders found, {len(new_rows)} new")

        if new_rows:
            conn.executemany("""
                INSERT OR IGNORE INTO orders
                (order_date, year, month, title, entity, violation_type, url, scraped_at)
                VALUES (:order_date,:year,:month,:title,:entity,:violation_type,:url,:scraped_at)
            """, new_rows)
            conn.commit()
            existing.update(r["url"] for r in new_rows)
            total_new += len(new_rows)

        url = get_next_url(resp.text)
        page_num += 1
        time.sleep(DELAY_S)

    total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    conn.close()
    print(f"\nDone. +{total_new} new | Total in DB: {total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=8,
                        help="Number of listing pages to fetch (25 orders each)")
    parser.add_argument("--all",   action="store_true",
                        help="Fetch all available pages (~480 pages)")
    args = parser.parse_args()
    pages = 480 if args.all else args.pages
    scrape(max_pages=pages)
