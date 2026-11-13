import json

from configs.multi_agent_ablation import CASES
from scripts.prepare_g6_readiness import historical_report
from src.evaluation.independent_final import ARMS


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
