import json

import pytest

from configs.multi_agent_ablation import CASES
from scripts.prepare_g6_readiness import historical_report
from src.evaluation.benchmark_io import wilson_rate
from src.evaluation.independent_final import ARMS, ReleaseRiskCriteria
from src.evaluation.independent_primary import _release_risk_gate
from src.evaluation.primary_metrics import ScoredCase, score_primary_metrics


def test_historical_risk_stays_inconclusive_even_with_no_errors(tmp_path):
    rows = [
        {"case_id": case.case_id, "answerable": bool(case.claims), "answered": bool(case.claims),
         "grounded_exact": bool(case.claims), "disposition": "VERIFIED" if case.claims else "ABSTAIN"}
        for case in CASES
    ]
    source = tmp_path / "historical.json"
    source.write_text(json.dumps({
        "configuration": {}, "peak_working_set_bytes": 0,
        "cohorts": {"m13": {name: {"per_case": rows, "overall": {}} for name in ARMS}},
    }), encoding="utf-8")
    result = historical_report(source)
    assert result["status"] == "PROVISIONAL_NOT_INDEPENDENT"
    assert result["paired_grounded_exact"]["answerable_pairs"] == 21
    for arm in result["arms"].values():
        assert arm["incorrect_release"]["numerator"] == 0
        assert arm["incorrect_release"]["denominator"] == 21
        assert arm["risk_claim"] == "INCONCLUSIVE"
        assert arm["failures"] == []


@pytest.mark.parametrize(("correct", "incorrect", "unjudged", "abstained", "expected"), [
    (21, 0, 0, 3, "INCONCLUSIVE"),
    (80, 0, 0, 20, "MEETS_DESCRIPTIVE_BOUND"),
    (79, 0, 1, 20, "INCONCLUSIVE"),
    (75, 5, 0, 20, "DOES_NOT_MEET"),
    (80, 0, 0, 81, "DOES_NOT_MEET"),
    (0, 0, 0, 10, "DOES_NOT_MEET"),
])
def test_release_gate_uses_frozen_coverage_and_missing_label_bounds(correct, incorrect, unjudged, abstained, expected):
    cases = [ScoredCase.model_validate({
        "case_id": f"correct-{index}", "answerable": True, "released": True, "answer_exact": True,
        "claims": ({"claim_id": "claim", "supported_by_context": True, "supported_by_citation_set": True,
                    "citations": ({"citation_id": "Source 1", "supports_claim": True},)},),
    }) for index in range(correct)]
    cases.extend(ScoredCase(case_id=f"incorrect-{i}", answerable=False, released=True) for i in range(incorrect))
    cases.extend(ScoredCase(case_id=f"unjudged-{i}", answerable=True, released=True) for i in range(unjudged))
    cases.extend(ScoredCase(case_id=f"abstained-{i}", answerable=True, released=False) for i in range(abstained))
    report = score_primary_metrics(cases)
    report["release_risk_intervals"] = {
        "all_releases_worst_case": wilson_rate(incorrect + unjudged, correct + incorrect + unjudged),
    }
    gate = _release_risk_gate(report, ReleaseRiskCriteria(minimum_coverage=0.5, maximum_incorrect_release=0.05))
    assert gate["status"] == expected
