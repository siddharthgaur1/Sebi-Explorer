"""Shared pytest fixtures for SEBI Explorer tests.

`src/app.py` is a Streamlit script that runs top-to-bottom on import,
including a `load_data()` DB query at module scope — so a plain `from app
import extract_penalty_cr` crashes at collection time in a fresh checkout
with no database yet. This ensures an empty, schema-correct DB exists
*before* any test module imports `app`, since conftest.py runs first.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

_DB_PATH = Path(__file__).parent.parent / "data" / "sebi_orders.db"
if not _DB_PATH.exists():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(_DB_PATH)
    _conn.executescript("""
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
    """)
    _conn.close()
