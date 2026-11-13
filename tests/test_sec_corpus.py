from datetime import date
from unittest.mock import Mock

import pytest

from src.ingestion.sec_corpus import SourceCache, filings_from_submissions, revision_links


def test_offline_source_cache_verifies_content(tmp_path):
    url = "https://www.sec.gov/Archives/filing.zip"
    client = Mock()
    client.fetch_bounded.return_value = b"filing"
    path, receipt = SourceCache(tmp_path, client).source(url, 16)
    assert path.suffix == ".zip"
    assert SourceCache(tmp_path, None).source(url, 16) == (path, receipt)
    client.fetch_bounded.assert_called_once_with(url, max_bytes=16)
    path.write_bytes(b"forged")
    with pytest.raises(ValueError, match="Corrupt"):
        SourceCache(tmp_path, None).source(url, 16)


def test_submissions_filter_and_revision_relationship():
    payload = {"cik": 320193, "filings": {"recent": {
        "form": ["10-K", "10-K/A", "10-K", "8-K"],
        "accessionNumber": ["0000320193-24-000099", "0000320193-25-000103", "0000320193-25-000100", "0000320193-25-000102"],
        "filingDate": ["2024-12-31", "2025-12-05", "2025-10-31", "2025-12-04"],
        "reportDate": ["2024-09-28", "2025-09-27", "2025-09-27", "2025-12-04"],
        "primaryDocument": ["old.htm", "aapl-a.htm", "aapl.htm", "../unsafe.htm"],
    }}}
    rows = filings_from_submissions(payload, cik=320193, ticker="AAPL", cutoff=date(2025, 12, 31),
                                    forms=frozenset({"10-K", "10-K/A", "8-K"}))
    assert [row.form_type for row in rows] == ["10-K/A", "10-K"]
    assert revision_links(rows)[rows[0].accession_number] == {
        "status": "UNIQUE_SAME_PERIOD_FORM", "original_accession": rows[1].accession_number,
    }
    assert revision_links(rows[:1])[rows[0].accession_number]["status"] == "UNRESOLVED"
    with pytest.raises(ValueError, match="CIK mismatch"):
        filings_from_submissions(payload, cik=789019, ticker="MSFT", cutoff=date(2025, 12, 31),
                                 forms=frozenset({"10-K"}))


def test_current_report_item_is_exact_and_keeps_periodic_filings():
    payload = {"cik": 320193, "filings": {"recent": {
        "form": ["8-K", "8-K", "8-K/A", "10-K"],
        "accessionNumber": [f"0000320193-25-{number:06d}" for number in (1, 2, 3, 4)],
        "filingDate": ["2025-11-01", "2025-11-02", "2025-11-03", "2025-11-04"],
        "reportDate": ["2025-11-01", "2025-11-01", "2025-11-01", "2025-09-27"],
        "primaryDocument": ["aapl1.htm", "aapl2.htm", "aapl3.htm", "aapl4.htm"],
        "items": ["9.01, 2.02", "5.02,9.01", "2.02", ""],
    }}}
    rows = filings_from_submissions(
        payload, cik=320193, ticker="AAPL", cutoff=date(2025, 12, 31),
        forms=frozenset({"10-K", "8-K", "8-K/A"}), current_report_item="2.02",
    )
    assert [row.form_type for row in rows] == ["10-K", "8-K/A", "8-K"]
    assert rows[-1].primary_document == "aapl1.htm"
