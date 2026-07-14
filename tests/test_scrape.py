"""Tests for scripts/scrape.py — violation classification, entity extraction,
and HTML parsing. No network calls; all fixtures are static HTML strings."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from scrape import classify, extract_entity, get_next_url, parse_listing_page


class TestClassify:
    def test_matches_insider_trading(self):
        assert classify("Adjudication Order in the matter of Insider Trading in XYZ Ltd") == "Insider Trading"

    def test_matches_market_manipulation(self):
        assert classify("Order against ABC for manipulating the share price") == "Market Manipulation"

    def test_matches_front_running(self):
        assert classify("Front running case against a fund manager") == "Front Running"

    def test_case_insensitive(self):
        assert classify("INSIDER TRADING VIOLATION") == "Insider Trading"

    def test_unmatched_title_returns_other(self):
        assert classify("Routine administrative notice") == "Other"


class TestExtractEntity:
    def test_extracts_entity_after_against(self):
        entity = extract_entity("Adjudication Order against Reliance Capital Ltd in the matter of disclosure violation")
        assert "Reliance Capital" in entity

    def test_extracts_entity_after_matter_of(self):
        entity = extract_entity("Order in the matter of XYZ Securities - insider trading")
        assert "XYZ Securities" in entity

    def test_no_match_returns_empty_string(self):
        assert extract_entity("Notice") == ""

    def test_extracted_entity_within_length_bounds(self):
        entity = extract_entity("Order against " + "A" * 200 + " for fraud")
        # Entities outside the 3-80 char bound should be rejected (returns "").
        assert entity == "" or len(entity) < 80


class TestParseListingPage:
    SAMPLE_HTML = """
    <table>
      <tr>
        <td>Jan 15, 2024</td>
        <td><a href="/orders/ao-123.pdf">Adjudication Order against ABC Ltd in the matter of Insider Trading</a></td>
      </tr>
      <tr>
        <td>Feb 03, 2024</td>
        <td><a href="https://www.sebi.gov.in/orders/ao-456.pdf">Order against XYZ Corp for Market Manipulation</a></td>
      </tr>
      <tr><td>Header only row</td></tr>
    </table>
    """

    def test_parses_rows_with_dates_and_links(self):
        rows = parse_listing_page(self.SAMPLE_HTML)
        assert len(rows) == 2

    def test_parses_date_into_iso_format(self):
        rows = parse_listing_page(self.SAMPLE_HTML)
        assert rows[0]["order_date"] == "2024-01-15"
        assert rows[0]["year"] == 2024
        assert rows[0]["month"] == "January"

    def test_resolves_relative_url_against_base(self):
        rows = parse_listing_page(self.SAMPLE_HTML)
        assert rows[0]["url"] == "https://www.sebi.gov.in/orders/ao-123.pdf"

    def test_preserves_absolute_url_unchanged(self):
        rows = parse_listing_page(self.SAMPLE_HTML)
        assert rows[1]["url"] == "https://www.sebi.gov.in/orders/ao-456.pdf"

    def test_classifies_violation_type_per_row(self):
        rows = parse_listing_page(self.SAMPLE_HTML)
        assert rows[0]["violation_type"] == "Insider Trading"
        assert rows[1]["violation_type"] == "Market Manipulation"

    def test_row_without_link_is_skipped(self):
        rows = parse_listing_page(self.SAMPLE_HTML)
        # The "Header only row" has no <a> tag and must not produce a row.
        assert all(r["title"] for r in rows)


class TestGetNextUrl:
    def test_finds_next_page_number(self):
        html = '<a href="javascript:searchFormNewsList(\'n\', \'3\')">Next</a>'
        next_url = get_next_url(html)
        assert next_url is not None
        assert "pageNum=3" in next_url

    def test_no_next_link_returns_none(self):
        assert get_next_url("<div>No pagination here</div>") is None
