"""Compare identity-matched SEC observations and build provisional cohorts."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from src.ingestion.company_facts import normalize_cik

ISO_USD = "{http://www.xbrl.org/2003/iso4217}USD"

# Use a fixed mapping and fixed period/filing filters before observing values.
METRICS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue from contracts with customers",
    "NetIncomeLoss": "net income attributable to the parent",
    "OperatingIncomeLoss": "operating income",
    "GrossProfit": "gross profit",
    "Assets": "total assets",
    "AssetsCurrent": "current assets",
    "AssetsNoncurrent": "noncurrent assets",
    "Liabilities": "total liabilities",
    "LiabilitiesCurrent": "current liabilities",
    "LiabilitiesNoncurrent": "noncurrent liabilities",
    "StockholdersEquity": "equity attributable to the parent",
    "CashAndCashEquivalentsAtCarryingValue": "cash and cash equivalents",
    "NetCashProvidedByUsedInOperatingActivities": "net cash from operating activities",
    "NetCashProvidedByUsedInInvestingActivities": "net cash from investing activities",
    "NetCashProvidedByUsedInFinancingActivities": "net cash from financing activities",
    "PaymentsToAcquirePropertyPlantAndEquipment": "payments to acquire property, plant and equipment",
    "CostOfRevenue": "cost of revenue",
    "ResearchAndDevelopmentExpense": "research and development expense",
    "IncomeTaxExpenseBenefit": "income tax expense",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
        "income from continuing operations before income taxes",
    "AccountsReceivableNetCurrent": "current net accounts receivable",
    "InventoryNet": "net inventory",
    "PropertyPlantAndEquipmentNet": "net property, plant and equipment",
    "RetainedEarningsAccumulatedDeficit": "retained earnings or accumulated deficit",
    "SellingGeneralAndAdministrativeExpense": "selling, general and administrative expense",
    "OperatingExpenses": "operating expenses",
}


def company_facts_values(payload: dict, cik: str, accession: str, *, currency: str = "USD") -> dict:
    if normalize_cik(payload["cik"]) != cik:
        raise ValueError("Company Facts CIK mismatch")
    values = defaultdict(set)
    for tag, concept in payload["facts"].get("us-gaap", {}).items():
        for observation in concept["units"].get(currency, ()):
            if observation.get("accn") == accession:
                values[tag, observation.get("start"), observation["end"]].add(Decimal(str(observation["val"])))
    return values


def compare_filing(facts: list[dict], company_facts: dict, filing: dict) -> list[dict]:
    cik = normalize_cik(filing["cik"])
    accession = filing["accession_number"]
    controls = company_facts_values(company_facts, cik, accession)
    grouped = defaultdict(list)
    for row in facts:
        key = row["identity"]
        if key["cik"] != cik or key["accession"] != accession:
            raise ValueError("Inline observation disagrees with filing identity")
        if (not key["concept"].startswith("{http://fasb.org/us-gaap/")
                or tuple(key["unit_numerator"]) != (ISO_USD,) or key["unit_denominator"]
                or key["dimensions"] or key["target"]):
            continue
        tag = key["concept"].split("}", 1)[1]
        grouped[tag, key["start"], key["end"]].append(row)
    results = []
    for (tag, start, end), observations in sorted(grouped.items(), key=lambda item: (
        item[0][0], item[0][1] or "", item[0][2],
    )):
        left = {Decimal(item["value"]) for item in observations}
        right = controls.get((tag, start, end), set())
        if not right:
            status = "MISSING_COMPANY_FACTS"
        elif len(left) > 1 or len(right) > 1:
            status = "CONFLICT"
        else:
            status = "EXACT" if left == right else "MISMATCH"
        results.append({
            "cik": cik, "ticker": filing["ticker"], "accession": accession, "form": filing["form_type"],
            "report_date": filing["report_date"], "tag": tag, "start": start, "end": end,
            "inline_values": sorted(str(value) for value in left),
            "company_facts_values": sorted(str(value) for value in right),
            "status": status, "fact_ids": sorted({row["fact_id"] for row in observations}),
            "source_urls": sorted({row["source_url"] for row in observations}),
        })
    return results


def build_cohorts(rows: list[dict], membership: dict[str, set[str]], limits: dict[str, int]) -> dict:
    seen = set()
    for tickers in membership.values():
        if seen.intersection(tickers):
            raise ValueError("Issuer membership overlaps across cohorts")
        seen.update(tickers)
    cohorts = {}
    for name, tickers in membership.items():
        cases = []
        for row in rows:
            if (row["ticker"] not in tickers or len(row["inline_values"]) != 1 or row["tag"] not in METRICS
                    or row["end"] != row["report_date"] or row["form"] not in {"10-K", "10-Q"}):
                continue
            period = f"from {row['start']} to {row['end']}" if row["start"] else f"as of {row['end']}"
            cases.append({
                "case_id": f"{row['accession']}:{row['tag']}:{row['start'] or 'instant'}:{row['end']}",
                "question": f"What was {row['ticker']}'s consolidated {METRICS[row['tag']]} {period} "
                            f"in its {row['form']} filing {row['accession']}, in USD?",
                "category": "lookup",
                "label_provenance": "AUTO_XBRL",
                "issuer_cik": row["cik"], "accession": row["accession"],
                "tag": row["tag"], "period_start": row["start"], "period_end": row["end"],
                "revision_family": [row["cik"], row["form"], row["report_date"]],
                "evidence_fact_ids": row["fact_ids"], "evidence_urls": row["source_urls"],
                "gold_value_usd": row["inline_values"][0],
            })
        by_issuer = defaultdict(list)
        for case in cases:
            by_issuer[case["issuer_cik"]].append(case)
        # Interleave issuer groups before taking the fixed cohort size.
        cohorts[name] = [
            group[index]
            for index in range(max(map(len, by_issuer.values()), default=0))
            for _, group in sorted(by_issuer.items())
            if index < len(group)
        ][:limits[name]]
    assert_cohort_disjoint(cohorts)
    return cohorts


def assert_cohort_disjoint(cohorts: dict[str, list[dict]]) -> None:
    all_case_ids = [case["case_id"] for cases in cohorts.values() for case in cases]
    if len(set(all_case_ids)) != len(all_case_ids):
        raise ValueError("Duplicate case ID")
    for key in ("case_id", "issuer_cik", "accession", "revision_family", "evidence_fact_ids", "evidence_urls"):
        seen = set()
        for cases in cohorts.values():
            if key in {"evidence_fact_ids", "evidence_urls"}:
                values = {value for case in cases for value in case[key]}
            else:
                values = {tuple(case[key]) if isinstance(case[key], list) else case[key] for case in cases}
            if seen & values:
                raise ValueError(f"Cohort overlap for {key}")
            seen.update(values)
