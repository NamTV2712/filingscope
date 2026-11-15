"""Replay filed, restated and recast values against SEC source cells."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile

from lxml import etree

from configs.offline_guard import offline_socket_guard
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.sec_ixbrl_evaluation import ISO_USD, company_facts_values
from src.ingestion.company_facts import normalize_cik
from src.ingestion.inline_xbrl import Dimension, FactIdentity, resolve_inline_fact
from src.ingestion.sec_client import FilingMetadata
from src.ingestion.sec_corpus import MAX_ARCHIVE_BYTES, MAX_METADATA_BYTES, SourceCache
from src.retrieval.canonical_json import sha256_file

MASSIMO_ORIGINAL = "0001641172-25-000763"
MASSIMO_AMENDMENT = "0001641172-25-011711"
REDFIN_ORIGINAL = "0001382821-25-000046"
REDFIN_AMENDMENT = "0001104659-25-039439"
US_GAAP = "{http://fasb.org/us-gaap/2024}"
SRT = "{http://fasb.org/srt/2024}"
REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"
PREVIOUSLY_REPORTED = Dimension(SRT + "RestatementAxis", "explicit", SRT + "ScenarioPreviouslyReportedMember", "segment")
ADJUSTMENT = replace(PREVIOUSLY_REPORTED, member=SRT + "RevisionOfPriorPeriodReclassificationAdjustmentMember")
SEGMENT_AXIS = US_GAAP + "StatementBusinessSegmentsAxis"
REDFIN = "{http://www.redfin.com/20241231}"
RECAST_DIMENSIONS = (PREVIOUSLY_REPORTED, Dimension(SEGMENT_AXIS, "explicit", REDFIN + "TitleMember", "segment"),
                     Dimension(SEGMENT_AXIS, "explicit", REDFIN + "MonetizationMember", "segment"))

# The amounts and anchor locations come from the displayed SEC statements and notes.
RESTATEMENT_ROWS = (
    (REVENUE, 111_209_142, 109_325_742, -1_883_400, (214, 217, 682, 683, 684)),
    ("GrossProfit", 34_343_339, 32_459_939, -1_883_400, (220, 223, 686, 687, 688)),
    ("OperatingIncomeLoss", 6_811_991, 5_049_589, -1_762_402, (241, 244, 698, 699, 700)),
    ("NetIncomeLoss", 3_154_207, 1_761_909, -1_392_298, (265, 268, 710, 711, 712)),
)
RECAST_ROWS = (
    ("Year Ended December 31, 2022", "2022-01-01", "2022-12-31", (23_684, 17_425, 6_259)),
    ("Year Ended December 31, 2023", "2023-01-01", "2023-12-31", (39_175, 25_095, 14_080)),
    ("Three Months Ended March 31, 2024", "2024-01-01", "2024-03-31", (10_962, 6_513, 4_449)),
    ("Three Months Ended June 30, 2024", "2024-04-01", "2024-06-30", (16_528, 11_505, 5_023)),
    ("Three Months Ended September 30, 2024", "2024-07-01", "2024-09-30", (15_598, 10_394, 5_204)),
)


def _identity(filing, concept, start, end, dimensions=()):
    revision = "AMENDMENT" if filing.form_type.endswith("/A") else "FILED"
    return FactIdentity(normalize_cik(filing.cik), US_GAAP + concept, start, end, (ISO_USD,), (), dimensions,
                        filing.accession_number, revision, "")


def _check(observations, filing, identity, expected_usd, anchor):
    result = resolve_inline_fact(observations, identity, filing=filing)
    source = f"{filing.filing_url}#{anchor}"
    return {"identity": asdict(identity), "fact_id": identity.fact_id, "source_url": source,
            "expected_usd": expected_usd, "actual_usd": str(result.value) if result.value is not None else None,
            "exact": result.value == expected_usd and source in result.source_urls, "status": result.reason}


def _restatement(filings, facts, comparable):
    start, end = "2024-01-01", "2024-12-31"
    checks = []
    for concept, before, after, delta, anchors in RESTATEMENT_ROWS:
        matched = []
        negatives = {}
        for i, (basis, accession, expected, dimensions) in enumerate((
            ("ORIGINAL_STATEMENT", MASSIMO_ORIGINAL, before, ()),
            ("RESTATED_STATEMENT", MASSIMO_AMENDMENT, after, ()),
            ("PREVIOUSLY_REPORTED", MASSIMO_AMENDMENT, before, (PREVIOUSLY_REPORTED,)),
            ("ADJUSTMENT", MASSIMO_AMENDMENT, delta, (ADJUSTMENT,)),
            ("RESTATED_BRIDGE", MASSIMO_AMENDMENT, after, ()),
        )):
            filing = filings[accession]
            identity = _identity(filing, concept, start, end, dimensions)
            check = _check(facts[accession], filing, identity, expected, f"Fact{anchors[i]:06d}")
            matched.append({"basis": basis, **check})
            if i < 2:
                other = filings[MASSIMO_AMENDMENT if accession == MASSIMO_ORIGINAL else MASSIMO_ORIGINAL]
                for field, value in (("accession", other.accession_number),
                                     ("revision", "FILED" if identity.revision == "AMENDMENT" else "AMENDMENT")):
                    resolved = resolve_inline_fact(facts[accession], replace(identity, **{field: value}), filing=filing)
                    negatives[f"{basis}:{field}"] = resolved.reason
        bridge_exact = False
        if all(item["exact"] for item in matched):
            original, restated, _, adjustment, _ = (Decimal(item["actual_usd"]) for item in matched)
            bridge_exact = restated - original == adjustment
        checks.append({
            "concept": concept, "observations": matched, "wrong_identity_results": negatives,
            "bridge_signed_delta_exact": bridge_exact,
            "company_facts_exact": {acc: comparable[acc].get((concept, start, end), set()) == {value}
                                    for acc, value in ((MASSIMO_ORIGINAL, before), (MASSIMO_AMENDMENT, after))},
        })
    return checks


def _recast(entry, filing, observations, cache):
    path, receipt = cache.source(entry["archive"]["url"], MAX_ARCHIVE_BYTES)
    if receipt != entry["archive"]:
        raise ValueError("Redfin archive receipt differs from the manifest")
    with ZipFile(path) as archive:
        content = archive.read(filing.primary_document)
    root = etree.fromstring(content, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    tables = {}
    for table in root.xpath("//*[local-name()='table']"):
        rows = table.xpath(".//*[local-name()='tr']")
        lines = [" ".join(" ".join(row.itertext()).split()) for row in rows]
        if len(lines) < 5 or lines[2:4] != ["Previously reported Recast", "Other Title Monetization"]:
            continue
        tables.setdefault(lines[1], []).append(rows[4])

    results = []
    for heading, start, end, reference in RECAST_ROWS:
        row, = tables[heading]
        cells = [cell for cell in row if cell.text is not None or len(cell)]
        labels = ["".join(cell.itertext()).strip() for cell in cells]
        if labels[0] != "Revenue":
            raise ValueError(f"Expected the disclosed revenue row for {heading}")
        amounts = [(int(label.replace(",", "")), cell) for label, cell in zip(labels, cells, strict=True)
                   if label.replace(",", "").isdigit()]
        if tuple(amount for amount, _ in amounts) != reference:
            raise ValueError(f"Redfin displayed revenue disagrees with the reference for {heading}")
        reported, title, monetization = reference
        checks = []
        for (amount, cell), scope, dimension in zip(amounts, ("Previously reported Other", "Recast Title", "Recast Monetization"),
                                                      RECAST_DIMENSIONS, strict=True):
            anchor_nodes = cell.xpath(".//*[local-name()='nonFraction']")
            if not anchor_nodes:
                checks.append({"scope": scope, "expected_usd": amount * 1000, "status": "CELL_UNTAGGED"})
                continue
            node, = anchor_nodes
            if not node.get("id"):
                raise ValueError(f"Missing source anchor for {heading}, {scope}")
            identity = _identity(filing, REVENUE, start, end, (dimension,))
            checks.append({"scope": scope, **_check(observations, filing, identity, amount * 1000, node.get("id"))})
        results.append({"heading": heading, "start": start, "end": end, "observations": checks,
                        "displayed_split_reconciles": reported == title + monetization})
    return results


def evaluate(corpus: Path, cache_path: Path) -> dict:
    manifest_path = corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("schema") != "filingscope-sec-ixbrl-corpus-v1":
        raise ValueError("Expected a SEC Inline XBRL corpus manifest")
    entries = {entry["accession_number"]: entry for entry in manifest["filings"]}
    cache = SourceCache(cache_path, None)
    filings, facts, comparables = {}, {}, {}
    for issuer in manifest["issuers"]:
        receipt = issuer["company_facts"]
        company_path, actual = cache.source(receipt["url"], MAX_METADATA_BYTES)
        if receipt != actual:
            raise ValueError("Company Facts receipt differs from the manifest")
        payload = json.loads(company_path.read_bytes(), parse_float=Decimal)
        for entry in entries.values():
            if normalize_cik(entry["cik"]) != issuer["cik"]:
                continue
            filing = FilingMetadata(**{key: entry[key] for key in FilingMetadata.__dataclass_fields__})
            accession = filing.accession_number
            path = corpus / "facts" / f"{accession}.json"
            if sha256_file(path) != entry["facts_sha256"]:
                raise ValueError(f"Changed Inline XBRL observations for {accession}")
            filings[accession] = filing
            facts[accession] = json.loads(path.read_bytes())["facts"]
            comparables[accession] = company_facts_values(payload, issuer["cik"], accession)
    for original, amendment in ((MASSIMO_ORIGINAL, MASSIMO_AMENDMENT), (REDFIN_ORIGINAL, REDFIN_AMENDMENT)):
        if entries[amendment].get("amendment_relationship") != {
            "original_accession": original, "status": "UNIQUE_SAME_PERIOD_FORM",
        }:
            raise ValueError(f"Missing original filing link for {amendment}")
    return {"status": "PROVISIONAL_NOT_INDEPENDENT", "label_source": "AUTHOR_REVIEWED_SEC_HTML",
            "corpus_manifest_sha256": sha256_file(manifest_path),
            "massimo": _restatement(filings, facts, comparables),
            "redfin": _recast(entries[REDFIN_ORIGINAL], filings[REDFIN_ORIGINAL], facts[REDFIN_ORIGINAL], cache)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output file")
    started = perf_counter()
    with offline_socket_guard():
        report = evaluate(args.corpus, args.cache)
        write_json_atomic(args.output, report)
    print(json.dumps({"wall_ms": round(1000 * (perf_counter() - started), 3), "peak_memory_bytes": peak_memory_bytes(),
                      "model_calls": 0, "cost_usd": 0}))


if __name__ == "__main__":
    main()
