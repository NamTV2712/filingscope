from unittest.mock import Mock

import pytest

from scripts.run_g5_groq_observer import MODEL, _compare, _request
from src.evaluation.evidence_policy_benchmark import evidence_policy_scenarios
from src.policy.decision_backend import DeterministicDecisionBackend
from src.policy.evidence_policy import CandidateDisposition


def test_groq_benchmark_preserves_hard_reject_and_falls_back_on_invalid_reply(tmp_path):
    scenarios = evidence_policy_scenarios()
    backend = DeterministicDecisionBackend()
    hard_reject = next(case for case in scenarios if case.expected_disposition == CandidateDisposition.REJECT)
    accept = next(case for case in scenarios if case.expected_disposition == CandidateDisposition.ACCEPT)
    plan = [
        {"payload": _request("What was FY2024 revenue?", "TEST_10K", "Annual net sales were USD 2 million."),
         "case_id": case.case_id, "source": "TEST_10K#p2", "split": "development", "gold_supports_slot": supported,
         "baseline": backend.decide(case.features)}
        for case, supported in ((hard_reject, False), (accept, True))
    ]
    session = Mock()
    session.post.side_effect = [Mock(status_code=200, **{"json.return_value": {
        "model": MODEL, "usage": {"prompt_tokens": 100, "completion_tokens": 12},
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
    }}) for content in ('{"relevance":"relevant"}', '{"relevance":"irrelevant","authority":"reject"}')]
    report = {"observations": []}
    _compare(plan, session, report, tmp_path / "report.json")
    reject, fallback = report["observations"]
    assert reject["baseline"] == reject["observed"] == CandidateDisposition.REJECT
    assert fallback["baseline"] == fallback["observed"] == CandidateDisposition.ACCEPT
    assert report["summary"]["provider_errors"] == 1
    assert report["summary"]["observer_false_support"] == 1
    assert report["summary"]["hard_rejections_weakened"] == 0


@pytest.mark.parametrize("status", [401, 402, 403])
def test_observer_benchmark_stops_on_account_errors(tmp_path, status):
    baseline = DeterministicDecisionBackend().decide(evidence_policy_scenarios()[0].features)
    planned = {"payload": {}, "case_id": "case", "source": "FILING#p1", "split": "development",
               "gold_supports_slot": True, "baseline": baseline}
    session = Mock()
    session.post.return_value = Mock(status_code=status, headers={})
    report = {"observations": []}
    _compare([planned, planned], session, report, tmp_path / "report.json")
    assert session.post.call_count == 1
    assert report["halted"] == f"http_{status}" and report["status"] == "INCOMPLETE_PROVIDER_RUN"
    assert report["observations"][0]["baseline"] == report["observations"][0]["observed"]
