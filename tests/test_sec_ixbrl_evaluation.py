from copy import deepcopy

import pytest

from src.evaluation.sec_ixbrl_evaluation import ISO_USD, assert_cohort_disjoint, build_cohorts, compare_filing


def test_comparison_does_not_mix_periods_units_or_accessions():
    filing = {"ticker": "AAPL", "cik": 320193, "form_type": "10-K",
              "accession_number": "0000320193-25-000079", "report_date": "2025-09-27"}
    identity = {
        "cik": "0000320193", "accession": filing["accession_number"], "target": "",
        "concept": "{http://fasb.org/us-gaap/2025}Assets", "start": None, "end": filing["report_date"],
        "unit_numerator": (ISO_USD,), "unit_denominator": (), "dimensions": (),
    }
    fact = {"identity": identity, "value": "12", "fact_id": "id", "source_url": "https://www.sec.gov/sample.htm#f"}
    control = {"cik": 320193, "facts": {"us-gaap": {"Assets": {"units": {"USD": [
        {"accn": filing["accession_number"], "end": filing["report_date"], "val": 12},
        {"accn": "0000320193-24-000079", "end": filing["report_date"], "val": 99},
        {"accn": filing["accession_number"], "end": "2024-09-28", "val": 70},
    ]}}}}}
    segment = {**fact, "identity": {**identity, "dimensions": ("segment",)}, "value": "15"}
    row, = compare_filing([fact, segment], control, filing)
    assert row["status"] == "EXACT"
    conflict, = compare_filing([fact, {**fact, "value": "13"}], control, filing)
    assert conflict["status"] == "CONFLICT"
    cohorts = build_cohorts([row], {"pilot": {"AAPL"}, "validation": {"MSFT"}}, {"pilot": 1, "validation": 1})
    assert cohorts["pilot"][0]["label_provenance"] == "AUTO_XBRL"
    assert not cohorts["validation"]
    other = {**cohorts["pilot"][0], "case_id": "other"}
    with pytest.raises(ValueError, match="issuer_cik"):
        assert_cohort_disjoint({**cohorts, "validation": [other]})
    wrong_cik = deepcopy(fact)
    wrong_cik["identity"]["cik"] = "0000789019"
    with pytest.raises(ValueError, match="filing identity"):
        compare_filing([wrong_cik], control, filing)
