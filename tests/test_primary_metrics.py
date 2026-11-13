import json
import sys
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from scripts.run_primary_metrics import main
from src.evaluation.primary_metrics import NumericChecks, ScoredCase, score_primary_metrics

FIXTURE = Path(__file__).parent / "fixtures/g1_adjudications.json"


def _cases():
    return TypeAdapter(list[ScoredCase]).validate_json(FIXTURE.read_bytes())


def test_primary_metrics_cli_scores_the_fixed_cases(monkeypatch, tmp_path):
    output = tmp_path / "scores.json"
    monkeypatch.setattr(sys, "argv", ["run_primary_metrics", str(FIXTURE), "--output", str(output)])
    main()
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["scoring_version"] == "filingscope-primary-metrics-v1"
    assert result["case_count"] == 7
    primary = result["primary"]
    assert {metric: (r["numerator"], r["denominator"]) for metric, r in primary.items()} == {
        "grounded_exact_accuracy": (1, 4),
        "numeric_exact_accuracy": (1, 3),
        "answer_coverage": (5, 7),
        "incorrect_or_unsupported_release_risk": (3, 4),
        "citation_support_precision": (1, 3),
        "claim_faithfulness": (2, 3),
    }
    assert primary["numeric_exact_accuracy"]["eligible_cases"] == 4
    assert primary["incorrect_or_unsupported_release_risk"]["eligible_cases"] == 5
    assert result["diagnostics"]["unjudged_releases"] == 1
    assert result["diagnostics"]["release_risk_missing_label_bounds"] == {
        "denominator": 5, "minimum_errors": 3, "maximum_errors": 4, "lower": 0.6, "upper": 0.8,
    }
    assert result["diagnostics"]["false_abstention"]["value"] == 1 / 5
    assert result["diagnostics"]["correct_abstention"]["value"] == 1 / 2
    retrieval = result["retrieval_by_granularity"]
    assert retrieval["page"]["context_precision_at_10"] == {
        "numerator": 1, "denominator": 10, "value": 0.1, "applicable_cases": 3, "eligible_cases": 4,
    }
    assert retrieval["page"]["gold_evidence_recall_at_10"] == {
        "numerator": 1, "denominator": 3, "value": 1 / 3, "applicable_cases": 2, "eligible_cases": 4,
    }
    assert retrieval["fact"]["context_precision_at_10"]["value"] == 1
    assert retrieval["fact"]["gold_evidence_recall_at_10"]["value"] == 0.5
    assert result["resources"]["provider_calls"] == 0


@pytest.mark.parametrize("field", list(NumericChecks.model_fields))
def test_each_financial_identity_check_is_required(field):
    case = _cases()[0]
    labels = case.model_dump()
    labels["numeric_checks"][field] = False
    result = score_primary_metrics([ScoredCase.model_validate(labels)])
    assert result["primary"]["numeric_exact_accuracy"]["value"] == 0
    assert result["primary"]["incorrect_or_unsupported_release_risk"]["value"] == 1


def test_shared_sources_can_satisfy_multiple_gold_targets():
    case = ScoredCase.model_validate_json("""
    {"case_id":"shared-page","answerable":true,"released":false,"retrieval":{
        "granularity":"page","ranked_ids":["p1","p1"],"relevant_ids":["p1"],
        "gold_targets":{"revenue":["p1","p2"],"income":["p1","p3"]}
    }}
    """)
    result = score_primary_metrics([case])["retrieval_by_granularity"]["page"]
    assert result["context_precision_at_10"]["denominator"] == 1
    assert result["gold_evidence_recall_at_10"]["numerator"] == 2


def test_joint_citations_and_uncited_claims_use_distinct_denominators():
    case = ScoredCase.model_validate_json("""
    {"case_id":"joint-sources","answerable":true,"released":true,"answer_exact":true,"claims":[
        {"claim_id":"growth","supported_by_context":true,"supported_by_citation_set":true,
         "citations":[{"citation_id":"start","supports_claim":true},{"citation_id":"end","supports_claim":true}]},
        {"claim_id":"narrative","supported_by_context":true,"supported_by_citation_set":false,"citations":[]}
    ]}
    """)
    primary = score_primary_metrics([case])["primary"]
    assert primary["grounded_exact_accuracy"]["value"] == 0
    assert primary["citation_support_precision"]["denominator"] == 2
    assert primary["citation_support_precision"]["value"] == 1
    assert primary["claim_faithfulness"]["value"] == 1


def test_empty_batch_and_empty_references_are_undefined():
    assert all(value["value"] is None for value in score_primary_metrics([])["primary"].values())
    case = _cases()[4]
    result = score_primary_metrics([case])
    assert result["primary"]["incorrect_or_unsupported_release_risk"]["value"] is None
    assert result["retrieval_by_granularity"]["page"]["gold_evidence_recall_at_10"]["value"] is None


def test_duplicate_cases_and_duplicate_claim_citations_are_invalid():
    case = _cases()[0]
    with pytest.raises(ValueError, match="Duplicate case ID"):
        score_primary_metrics([case, case])
    labels = case.model_dump()
    citations = labels["claims"][0]["citations"]
    labels["claims"][0]["citations"] = citations + citations
    with pytest.raises(ValidationError, match="Duplicate claim-citation association"):
        ScoredCase.model_validate(labels)


def test_invalid_approval_labels_are_rejected():
    labels = _cases()[0].model_dump()
    labels["released"] = False
    with pytest.raises(ValidationError, match="require a release"):
        ScoredCase.model_validate(labels)
    labels["released"] = "true"
    with pytest.raises(ValidationError, match="valid boolean"):
        ScoredCase.model_validate(labels)
