"""Tests for src/app.py's penalty extraction (pure logic, no Streamlit/DB)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app import extract_penalty_cr


class TestExtractPenaltyCr:
    def test_extracts_crore_amount(self):
        assert extract_penalty_cr("SEBI imposes penalty of Rs. 5 crore on XYZ Ltd") == 5.0

    def test_extracts_lakh_amount_converted_to_crore(self):
        assert extract_penalty_cr("Fine of Rs. 50 lakh imposed on ABC Corp") == 0.5

    def test_extracts_rupee_symbol_amount(self):
        assert extract_penalty_cr("Penalty of ₹2.5 crore imposed") == 2.5

    def test_handles_comma_separated_amount(self):
        assert extract_penalty_cr("Penalty of Rs. 1,000 crore imposed") == 1000.0

    def test_no_penalty_mentioned_returns_none(self):
        assert extract_penalty_cr("Order regarding disclosure requirements") is None

    def test_case_insensitive_matching(self):
        assert extract_penalty_cr("PENALTY OF RS. 3 CRORE IMPOSED") == 3.0
