"""Build source-bound mixed QA cases from the frozen SEC comparison corpus."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from src.evaluation.sec_ixbrl_evaluation import ISO_USD, METRICS, company_facts_values
from src.ingestion.company_facts import normalize_cik
from src.ingestion.sec_corpus import MAX_ARCHIVE_BYTES, SourceCache
from src.retrieval.canonical_json import canonical_sha256, sha256_file


_NARRATIVE = {
    "AAPL": ("What are the reportable segments?", "Americas, Europe, Greater China, Japan and Rest of Asia Pacific",
             "The Company’s reportable segments consist of the Americas, Europe, Greater China, Japan and Rest of Asia Pacific."),
    "AMZN": ("How does the company organize its operations into segments?", "North America, International and AWS",
             "We have organized our operations into three segments: North America, International, and AWS."),
    "GOOG": ("Which businesses are reported in Google's two segments?", "Google Services and Google Cloud",
             "We report Google in two segments, Google Services and Google Cloud;"),
    "KO": ("What are the two lines of business?", "Concentrate operations and finished product operations",
           "Our Company operates in two lines of business: concentrate operations and finished product operations."),
    "MSFT": ("Which three segments does the company use to report financial performance?",
             "Productivity and Business Processes, Intelligent Cloud and More Personal Computing",
             "We operate our business and report our financial performance using three segments: Productivity and Business Processes, Intelligent Cloud, and More Personal Computing."),
    "NVDA": ("What are the two operating segments?", "Compute & Networking and Graphics",
             'Our two operating segments are "Compute & Networking" and "Graphics."'),
    "TSLA": ("What are the reportable segments?", "Automotive and energy generation and storage",
             "We operate as two reportable segments: (i) automotive and (ii) energy generation and storage."),
    "WMT": ("What are the reportable segments?", "Walmart U.S., Walmart International and Sam's Club U.S.",
            "Our operations comprise three reportable segments: Walmart U.S., Walmart International and Sam's Club U.S."),
}
_AMENDMENT_EXCERPT = (
    "amend Part III, Items 10, 11, 12, 13 and 14 of the Original Form 10-K to include the information required by such Items"
)
_EUR = ISO_USD.removesuffix("USD") + "EUR"
_CATEGORY_CAPS = {"multi_company": 6, "multi_period": 18, "quarter_ytd": 18, "hard_negative": 12}


def _document(filing: dict) -> dict:
    return {
        "ticker": filing["ticker"], "cik": normalize_cik(filing["cik"]), "accession": filing["accession_number"],
        "form": filing["form_type"], "filed": filing["filing_date"], "report_date": filing["report_date"],
        "revision_family": [normalize_cik(filing["cik"]), filing["form_type"].removesuffix("/A"), filing["report_date"]],
        "source_url": filing["source_url"], "archive_sha256": filing["archive"]["sha256"],
        "facts_sha256": filing["facts_sha256"],
    }


def _slot(row: dict) -> dict:
    return {"accession": row["accession"], "cik": row["cik"], "tag": row["tag"], "start": row["start"],
            "end": row["end"], "currency": "USD", "scale": "unit", "basis": "CONSOLIDATED", "value": row["inline_values"][0],
            "fact_ids": row["fact_ids"], "source_urls": row["source_urls"]}


def _identity(row: dict) -> tuple:
    return row["accession"], row["tag"], row["start"], row["end"]


def _case(category: str, question: str, documents: list[dict], rows: tuple[dict, ...] = (), **details) -> dict:
    return {
        "case_id": f"{category}-{canonical_sha256(question)[7:27]}", "category": category, "question": question,
        "answerable": category != "unanswerable", "label_provenance": "AUTO_XBRL",
        "documents": documents, "required_facts": [_slot(row) for row in rows],
        **details,
    }


def _source_excerpt(filing: dict, cache: SourceCache, excerpt: str) -> dict:
    path, receipt = cache.source(filing["archive"]["url"], MAX_ARCHIVE_BYTES)
    if receipt != filing["archive"]:
        raise ValueError("Archive receipt differs from the frozen manifest")
    with ZipFile(path) as bundle:
        root = etree.HTML(bundle.read(filing["primary_document"]))
    for element in root.xpath("//p|//div|//td|//li"):
        text = " ".join("".join(element.itertext()).split())
        if excerpt in text and len(text) <= 1500:
            return {"source_url": filing["source_url"], "archive_sha256": receipt["sha256"],
                    "member": filing["primary_document"], "excerpt": excerpt, "block_sha256": canonical_sha256(text)}
    raise ValueError(f"Missing source excerpt in {filing['accession_number']}")


def _eligible_rows(rows: list[dict], source_url: str) -> list[dict]:
    return [row for row in rows if row["tag"] in METRICS and len(row["inline_values"]) == 1
            and any(url.startswith(source_url + "#") for url in row["source_urls"])]


def _filing_rows(filing: dict, rows: list[dict], facts: list[dict], cache: SourceCache) -> dict[str, list[dict]]:
    doc = _document(filing)
    ticker, accession, end, form = (doc[key] for key in ("ticker", "accession", "report_date", "form"))
    eligible = _eligible_rows(rows, doc["source_url"])
    current = [row for row in eligible if row["end"] == end]
    by_tag = defaultdict(list)
    for row in eligible:
        if row["start"]:
            by_tag[row["tag"]].append(row)

    result = defaultdict(list)
    for tag, intervals in sorted(by_tag.items()):
        durations = [(row, (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days + 1)
                     for row in intervals]
        if form == "10-K":
            annual = [row for row, days in durations if 350 <= days <= 380]
            latest = [row for row in annual if row["end"] == end]
            if len(latest) == 1:
                prior = [row for row in annual
                         if (date.fromisoformat(latest[0]["start"]) - date.fromisoformat(row["end"])).days == 1]
                if len(prior) == 1:
                    previous = prior[0]
                    result["multi_period"].append(_case(
                        "multi_period", f"What consolidated {METRICS[tag]} did {ticker} report in USD for each of "
                        f"the fiscal years ended {previous['end']} and {end} in 10-K {accession}?",
                        [doc], (previous, latest[0]),
                    ))
        elif form == "10-Q":
            quarter = [row for row, days in durations if row["end"] == end and 75 <= days <= 105]
            ytd = [row for row, days in durations if row["end"] == end and 150 <= days <= 300]
            if len(quarter) == len(ytd) == 1 and ytd[0]["start"] < quarter[0]["start"]:
                result["quarter_ytd"].append(_case(
                    "quarter_ytd", f"What was {ticker}'s consolidated {METRICS[tag]} in USD for the standalone "
                    f"quarter and fiscal year to date ended {end} in 10-Q {accession}?",
                    [doc], (quarter[0], ytd[0]),
                ))

    dimensioned = defaultdict(list)
    for fact in facts:
        identity = fact["identity"]
        if (identity["dimensions"] and identity["unit_numerator"] == [ISO_USD] and not identity["unit_denominator"]
                and not identity["target"] and fact["source_anchor"]):
            tag = identity["concept"].rsplit("}", 1)[-1]
            dimensioned[tag, identity["start"], identity["end"]].append(fact)
    for row in current:
        tag = row["tag"]
        interval = f"from {row['start']} to {end}" if row["start"] else f"as of {end}"
        result["lookup"].append(_case(
            "lookup", f"What was {ticker}'s consolidated {METRICS[tag]} {interval} in {form} {accession}, in USD?",
            [doc], (row,),
        ))
        for distractor in dimensioned[tag, row["start"], end]:
            if (not distractor["identity"]["concept"].startswith("{http://fasb.org/us-gaap/")
                    or Decimal(distractor["value"]) == Decimal(row["inline_values"][0])):
                continue
            result["hard_negative"].append(_case(
                "hard_negative", f"What was {ticker}'s consolidated {METRICS[tag]} {interval} in {form} {accession} "
                "in USD, using the entity-wide figure?", [doc], (row,),
                distractor={key: distractor[key] for key in ("fact_id", "identity", "source_url", "value")},
            ))
            break

    if form == "10-K":
        prompt, answer, excerpt = _NARRATIVE[ticker]
        result["narrative"].append(_case(
            "narrative", f"According to {ticker}'s {form} {accession}, {prompt[0].lower() + prompt[1:]}", [doc],
            label_provenance="AUTHOR_CHECKED_FILING", expected_statement=answer,
            narrative_evidence=_source_excerpt(filing, cache, excerpt),
        ))
        for row in current:
            if row["tag"] != "OperatingIncomeLoss" or not row["start"]:
                continue
            requested = {"accession": accession, "cik": doc["cik"], "tag": row["tag"], "start": row["start"],
                         "end": end, "currency": "EUR", "basis": "CONSOLIDATED"}
            if any(fact["identity"]["unit_numerator"] == [_EUR] and not fact["identity"]["unit_denominator"]
                   and not fact["identity"]["dimensions"]
                   and fact["identity"]["end"] == end and fact["identity"]["start"] == row["start"]
                   and fact["identity"]["concept"].endswith("}OperatingIncomeLoss") for fact in facts):
                continue
            result["unanswerable"].append(_case(
                "unanswerable", f"What consolidated operating income in EUR is available in the frozen Inline XBRL "
                f"extract for {ticker} from {row['start']} to {end} in {form} {accession}?", [doc], missing_fact=requested,
                distractor=_slot(row),
            ))
    return result


def _company_cases(filings: list[dict], rows_by_accession: dict[str, list[dict]]) -> list[dict]:
    comparisons = []
    for left, right in combinations(sorted(filings, key=lambda item: item["ticker"]), 2):
        if left["cik"] == right["cik"]:
            continue
        docs = [_document(filing) for filing in (left, right)]
        selected = [
            {row["tag"]: row for row in _eligible_rows(rows_by_accession[doc["accession"]], doc["source_url"])
             if row["end"] == doc["report_date"] and row["start"] is None}
            for doc in docs
        ]
        companies = " and ".join(f"{doc['ticker']} as of {doc['report_date']} in 10-K {doc['accession']}" for doc in docs)
        for tag in sorted(selected[0].keys() & selected[1].keys()):
            comparisons.append(_case(
                "multi_company", f"What consolidated {METRICS[tag]} in USD did {companies} report?",
                docs, (selected[0][tag], selected[1][tag]),
            ))
    return comparisons


def _ordered(cases: list[dict]) -> list[dict]:
    by_issuer = defaultdict(list)
    for case in cases:
        by_issuer[tuple(doc["cik"] for doc in case["documents"])].append(case)
    return [group[index] for index in range(max(map(len, by_issuer.values()), default=0))
            for _, group in sorted(by_issuer.items()) if index < len(group)]


def assert_mixed_cohorts_disjoint(cohorts: dict[str, list[dict]]) -> None:
    ids = [case["case_id"] for cases in cohorts.values() for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate mixed case ID")
    seen = defaultdict(set)
    for cases in cohorts.values():
        current = defaultdict(set)
        for case in cases:
            for doc in case["documents"]:
                for key in ("cik", "accession", "source_url", "archive_sha256", "facts_sha256"):
                    current[key].add(doc[key])
                current["revision_family"].add(tuple(doc["revision_family"]))
            slots = list(case["required_facts"])
            if "distractor" in case:
                slots.append(case["distractor"])
            for slot in slots:
                current["fact_ids"].update(slot["fact_ids"] if "fact_ids" in slot else [slot["fact_id"]])
                current["source_urls"].update(slot["source_urls"] if "source_urls" in slot else [slot["source_url"]])
        for key, values in current.items():
            if seen[key] & values:
                raise ValueError(f"Mixed cohort overlap for {key}")
            seen[key].update(values)


def build_mixed_cohorts(
    rows: list[dict], filings: list[dict], corpus: Path, cache: SourceCache,
    membership: dict[str, set[str]], limits: dict[str, int], company_facts: dict[str, dict],
) -> tuple[dict[str, list[dict]], dict]:
    by_accession = defaultdict(list)
    for row in rows:
        by_accession[row["accession"]].append(row)
    if len({_identity(row) for row in rows}) != len(rows):
        raise ValueError("Duplicate numeric observation group in mixed cohort input")
    filings_by_accession = {filing["accession_number"]: filing for filing in filings}
    if len(filings_by_accession) != len(filings):
        raise ValueError("Duplicate accession in mixed cohort input")
    cohorts = {}
    for cohort, tickers in membership.items():
        eligible = [filing for filing in filings if filing["ticker"] in tickers]
        categories = defaultdict(list)
        for filing in eligible:
            accession = filing["accession_number"]
            path = corpus / "facts" / f"{accession}.json"
            if sha256_file(path) != filing["facts_sha256"]:
                raise ValueError(f"Inline XBRL extraction differs from frozen manifest for {accession}")
            if filing["form_type"] in {"10-K", "10-Q"}:
                facts = json.loads(path.read_bytes())["facts"]
                for category, cases in _filing_rows(filing, by_accession[accession], facts, cache).items():
                    categories[category].extend(cases)
            elif accession == "0001104659-25-042659":
                link = filing["amendment_relationship"]
                original = filings_by_accession[link["original_accession"]]
                if (link["status"] != "UNIQUE_SAME_PERIOD_FORM" or original["ticker"] != filing["ticker"]
                        or _document(original)["revision_family"] != _document(filing)["revision_family"]):
                    raise ValueError("Tesla amendment relationship disagrees with the frozen filing family")
                categories["revision"].append(_case(
                    "revision", f"Which items of Tesla's original 10-K did the explanatory note in 10-K/A {accession} say it amended?",
                    [_document(original), _document(filing)], label_provenance="AUTHOR_CHECKED_FILING",
                    expected_statement="Part III, Items 10 through 14",
                    narrative_evidence=_source_excerpt(filing, cache, _AMENDMENT_EXCERPT),
                ))
        categories["multi_company"] = _company_cases(
            [filing for filing in eligible if filing["form_type"] == "10-K"], by_accession,
        )
        required = {"lookup", "narrative", "unanswerable", *_CATEGORY_CAPS}
        if missing := required - {name for name, cases in categories.items() if cases}:
            raise ValueError(f"Missing mixed categories in {cohort}: {sorted(missing)}")

        selected = [*categories["narrative"], *categories["unanswerable"], *categories["revision"]]
        multi_slot = [_ordered(categories[name])[:cap] for name, cap in _CATEGORY_CAPS.items()]
        mixed_budget = limits[cohort] // 2
        selected.extend([group[index] for index in range(max(map(len, multi_slot)))
                         for group in multi_slot if index < len(group)][:mixed_budget])
        selected.extend(_ordered(categories["lookup"])[:max(0, limits[cohort] - len(selected))])
        if len(selected) != limits[cohort] or required - {case["category"] for case in selected}:
            raise ValueError(f"Mixed selection cannot satisfy the frozen plan for {cohort}")
        cohorts[cohort] = selected
    assert_mixed_cohorts_disjoint(cohorts)

    controls = {_identity(row): row for row in rows}
    summary = {}
    for cohort, cases in cohorts.items():
        metrics = defaultdict(Counter)
        for case in cases:
            counts = metrics[case["category"]]
            counts["cases"] += 1
            required_facts = case["required_facts"]
            if required_facts:
                groups = [controls[_identity(slot)] for slot in required_facts]
                released = all(len(row["company_facts_values"]) == 1 for row in groups)
                exact = all(row["status"] == "EXACT" for row in groups)
                counts["numeric_cases"] += 1
                counts["released"] += released
                counts["exact"] += exact
                counts["incorrect"] += released and not exact
                counts["abstained"] += not released
            elif missing_fact := case.get("missing_fact"):
                doc, = case["documents"]
                groups = company_facts_values(company_facts[doc["ticker"]], doc["cik"], doc["accession"],
                                              currency=missing_fact["currency"])
                observed = groups.get((missing_fact["tag"], missing_fact["start"], missing_fact["end"]), ())
                counts["missing_unit_controls"] += 1
                counts["correct_abstentions"] += len(observed) != 1
                counts["incorrect"] += len(observed) == 1
            else:
                counts["not_scored"] += 1
        summary[cohort] = dict(metrics)
    return cohorts, summary
