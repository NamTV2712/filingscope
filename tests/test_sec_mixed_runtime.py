from copy import deepcopy

from lxml import etree

from src.evaluation.sec_html_documents import filing_blocks
from src.evaluation.sec_mixed_runtime import score_mixed_release
from src.verification.response_policy import INSUFFICIENT_EVIDENCE_ANSWER


def test_sec_html_blocks_preserve_table_context_and_hide_metadata():
    root = etree.HTML(b"""<html><body><ix:header>hidden data</ix:header>
    <div>Consolidated Statements of Operations</div><div>(in millions)</div>
    <table><tr><td>Revenue</td><td>$</td><td>42</td></tr></table>
    <p>Visible <span>disclosure</span>.</p><div style='display:none'>hidden advice</div>
    </body></html>""")
    text = "\n".join(block for _, block in filing_blocks(root))
    assert "Consolidated Statements of Operations\n(in millions)\nRevenue  $  42" in text
    assert "Visible disclosure." in text
    assert "hidden" not in text


def test_mixed_runtime_checks_complete_financial_identity():
    accession = "0000320193-25-000079"
    slot = {"accession": accession, "cik": "0000320193", "tag": "OperatingIncomeLoss", "start": "2024-09-29",
            "end": "2025-09-27", "currency": "USD", "value": "42000000"}
    case = {"answerable": True, "required_facts": [slot]}
    answer = "Apple reported operating income of USD 42 million for FY2025. [Source 1]"
    claim = {"statement": answer, "status": "SUPPORTED", "supporting_evidence_ids": ["ev1"], "requirement_ids": ["r1"],
             "citations": [1]}
    record = {"evidence_id": "ev1", "period_identity": {"start": slot["start"], "end": slot["end"]},
              "currency": "USD", "normalized_value": "42000000", "cik": "320193", "xbrl_provenance": {
                  "accession": accession, "taxonomy": "us-gaap", "tag": "OperatingIncomeLoss",
              }}
    assert score_mixed_release(case, answer, "VERIFIED", [claim], [record], ["ev1"])["outcome"] == "confirmed_numeric_release"
    assert score_mixed_release(case, answer, "VERIFIED", [claim], [record], ["ev2"])["outcome"] == "numeric_release_identity_unconfirmed"
    for field, value in [("accession", "0000320193-24-000123"), ("tag", "NetIncomeLoss"), ("dimensions", [["segment", "a"]])]:
        wrong = deepcopy(record)
        wrong["xbrl_provenance"][field] = value
        assert score_mixed_release(case, answer, "VERIFIED", [claim], [wrong], ["ev1"])["outcome"] == "numeric_release_identity_unconfirmed"
    wrong_period = {**record, "period_identity": {"start": None, "end": slot["end"]}}
    assert score_mixed_release(case, answer, "VERIFIED", [claim], [wrong_period], ["ev1"])["outcome"] == "numeric_release_identity_unconfirmed"
    extra_citation = {**claim, "citations": [1, 2], "supporting_evidence_ids": ["ev1", "ev2"]}
    wrong_source = {**wrong_period, "evidence_id": "ev2"}
    result = score_mixed_release(case, answer, "VERIFIED", [extra_citation], [record, wrong_source], ["ev1", "ev2"])
    assert result["outcome"] == "numeric_release_identity_unconfirmed"
    assert score_mixed_release({"answerable": False}, INSUFFICIENT_EVIDENCE_ANSWER, "ABSTAIN", [], [], [])["outcome"] == "correct_abstention"
