import pytest

from src.research.corpus_map import (
    CorpusMap,
    MetadataCoverage,
    SourceAvailability,
)


def test_corpus_map_aggregates_only_metadata_and_marks_unindexed_sources():
    rows = [
        {
            "document_id": "ACME_2023_10K",
            "company": "Acme Corp",
            "doc_type": "10k",
            "reporting_periods": ["2023"],
            "section": "document",
            "chunk_index": 0,
            "text": "private filing text",
            "gold_pages": [9],
            "answer": "private benchmark answer",
        },
        {
            "document_id": "ACME_2023_10K",
            "company": "Acme Corp",
            "doc_type": "10k",
            "reporting_periods": ["2023"],
            "section": "document",
            "chunk_index": 1,
            "text": "more private filing text",
        },
    ]

    corpus_map = CorpusMap.from_chunks(
        rows,
        index_generation_id="index-123",
        collection_name="filings",
    )
    payload = corpus_map.runtime_payload()
    document = corpus_map.documents[0]

    assert corpus_map.index_generation_id == "index-123"
    assert corpus_map.chunk_count == 2
    assert len(corpus_map.documents) == 1
    assert document.document_id == "ACME_2023_10K"
    assert document.chunk_count == 2
    assert document.company_entity_ids == ("ACME",)
    assert document.form_types == ("10k",)
    assert document.filing_periods == ("2023",)
    assert corpus_map.metadata_coverage["company"] == MetadataCoverage.COMPLETE
    assert corpus_map.metadata_coverage["ticker"] == MetadataCoverage.NOT_INDEXED
    assert corpus_map.metadata_coverage["cik"] == MetadataCoverage.NOT_INDEXED
    assert corpus_map.metadata_coverage["table_id"] == MetadataCoverage.NOT_INDEXED
    assert corpus_map.source_coverage["filing_text"] == SourceAvailability.AVAILABLE
    assert corpus_map.source_coverage["structured_tables"] == SourceAvailability.MISSING
    assert corpus_map.source_coverage["xbrl_facts"] == SourceAvailability.UNKNOWN
    assert document.table_evidence == SourceAvailability.MISSING
    assert document.xbrl_evidence == SourceAvailability.UNKNOWN
    assert all("text" not in row for row in payload["documents"])
    assert all("gold_pages" not in row for row in payload["documents"])
    assert all("answer" not in row for row in payload["documents"])


def test_conflicted_metadata_downgrades_inventory_completeness():
    corpus_map = CorpusMap.from_chunks(
        [
            {
                "document_id": "ACME_2023_10K",
                "company": "Acme Corp",
                "doc_type": "10k",
                "reporting_periods": ["2023"],
                "section": "document",
                "metadata_conflicts": [{"field": "doc_type"}],
            }
        ]
    )

    assert corpus_map.metadata_coverage["form_type"] == MetadataCoverage.PARTIAL
    assert corpus_map.documents[0].metadata_conflicts == ("form_type",)


def test_form_type_variants_normalize_before_coverage_and_conflict_checks():
    corpus_map = CorpusMap.from_chunks(
        [
            {
                "document_id": "ACME_2023_10K",
                "company": "Acme Corp",
                "doc_type": "10k",
                "section": "document",
            },
            {
                "document_id": "ACME_2023_10K",
                "company": "Acme Corp",
                "doc_type": "Form 10-K",
                "section": "document",
            },
        ]
    )

    assert corpus_map.documents[0].form_types == ("10k",)
    assert "form_type" not in corpus_map.documents[0].metadata_conflicts
    assert corpus_map.metadata_coverage["form_type"] == MetadataCoverage.COMPLETE


def test_explicit_table_and_xbrl_inventory_is_preserved():
    corpus_map = CorpusMap.from_chunks(
        [
            {
                "document_id": "ACME_2023_10K",
                "company": "Acme Corp",
                "doc_type": "10k",
                "reporting_periods": ["2023"],
                "section": "document",
                "table_ids": ["table-1"],
                "has_xbrl_facts": False,
            }
        ]
    )

    assert corpus_map.documents[0].table_ids == ("table-1",)
    assert corpus_map.documents[0].table_evidence == SourceAvailability.AVAILABLE
    assert corpus_map.documents[0].xbrl_evidence == SourceAvailability.MISSING
    assert corpus_map.source_coverage["structured_tables"] == SourceAvailability.AVAILABLE
    assert corpus_map.source_coverage["xbrl_facts"] == SourceAvailability.MISSING
    assert corpus_map.metadata_coverage["table_id"] == MetadataCoverage.COMPLETE


def test_map_without_source_inventory_marks_absence_unknown():
    corpus_map = CorpusMap.from_chunks([{"document_id": "DOC_1"}])

    assert corpus_map.metadata_coverage["company"] == MetadataCoverage.NOT_INDEXED
    assert corpus_map.metadata_coverage["section"] == MetadataCoverage.NOT_INDEXED
    assert corpus_map.source_coverage["filing_text"] == SourceAvailability.UNKNOWN
    assert corpus_map.source_coverage["structured_tables"] == SourceAvailability.UNKNOWN


def test_chunk_without_document_identifier_is_rejected():
    with pytest.raises(ValueError, match="document_id or doc_name"):
        CorpusMap.from_chunks([{"company": "Acme Corp"}])
