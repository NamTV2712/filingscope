import pytest

from scripts.prepare_g6_exposure import _issuer_group, _membership, _resolve


def test_exposure_mapping_retains_historical_issuers_and_rejects_unknown_tickers():
    resolved = _resolve({"CTRA", "XOM", "AAPL"}, {"AAPL": 320193, "XOM": 2115436})
    assert resolved == {"AAPL": 320193, "CTRA": 858470, "XOM": 34088}
    assert _issuer_group(resolved, {"AAPL": 320193, "XOM": 2115436}) == {320193, 858470, 34088, 2115436}
    with pytest.raises(ValueError, match="Unresolved exposed tickers: UNKNOWN"):
        _resolve({"AAPL", "UNKNOWN"}, {"AAPL": 320193})


def test_exposure_membership_is_sorted_and_deduplicated():
    member = _membership("public", (3, 2, 3), ("z", "a", "z"), "2025-12-31")
    assert member.issuer_ciks == (2, 3)
    assert member.document_ids == ("a", "z")
    assert member.through.isoformat() == "2025-12-31"
