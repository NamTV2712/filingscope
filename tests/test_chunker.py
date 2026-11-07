from src.ingestion.chunker import build_chunks_for_filing, chunk_text, count_tokens


def test_chunk_text_respects_token_limit_and_preserves_all_sentences() -> None:
    sentences = [f"Revenue observation {index} increased." for index in range(40)]
    chunks = chunk_text(" ".join(sentences), chunk_size=12, overlap=3)

    assert len(chunks) > 1
    assert all(count_tokens(chunk) <= 12 for chunk in chunks)
    combined = " ".join(chunks)
    for index in range(40):
        assert f"observation {index}" in combined


def test_build_chunks_preserves_filing_identity_and_section_metadata() -> None:
    chunks = build_chunks_for_filing(
        {
            "ticker": "AAPL",
            "accession_number": "0000320193-24-000123",
            "filing_date": "2024-11-01",
            "report_date": "2024-09-28",
            "sections": {"business": "Apple designs and sells devices."},
        }
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "AAPL_000032019324000123_business_0000"
    assert chunks[0].section == "business"
    assert chunks[0].filing_date == "2024-11-01"
    assert chunks[0].report_date == "2024-09-28"
