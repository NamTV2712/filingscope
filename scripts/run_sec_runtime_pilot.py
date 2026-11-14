"""Replay identical PDF-labeled SEC questions with offline source inventories."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import time
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from configs.financebench import P1_EMBEDDING_REVISION
from configs.multi_agent_ablation import AblationCase, GoldClaim
from configs.offline_guard import offline_socket_guard
from configs.sec_runtime_pilot import CASES, NARRATIVE_CASES, PDFS, SEC_MANIFEST_SHA256, STATUS, NarrativeCase, PilotCase, StatementCell
from scripts.run_multi_agent_ablation import _PolicyLayer, _RecordingRetriever, _solo, _specialist_observation
from scripts.run_specialist_architectures import _adaptive
from src.agent.complexity_router import ComplexityRouter, ExecutionPath
from src.agent.specialist_graph import SpecialistResearchGraph
from src.decision.policy import EvidenceDecisionLayer
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.company_facts_replay import CompanyFactsReplay
from src.evaluation.multi_agent_ablation import AblationObservation, evaluate_observation, summarize_ablation
from src.evaluation.primary_metrics import RetrievalAdjudication, score_retrieval
from src.ingestion.company_facts import ResolvedCompanyFact
from src.ingestion.pdf_ingestion import chunk_pdf_pages, extract_pdf_pages
from src.ingestion.sec_corpus import MAX_METADATA_BYTES, SourceCache
from src.ingestion.segment_revenue import ENERGY_FILING, ENERGY_IDENTITY, load_energy_revenue
from src.research.corpus_map import CorpusMap
from src.retrieval.canonical_json import canonical_json_bytes, canonical_sha256, sha256_file
from src.retrieval.financial_statement_ranker import FinancialStatementRanker
from src.retrieval.frozen_dense import FrozenDenseRetriever
from src.retrieval.pdf_page_cache import FrozenPdfPages

TRACKS = {"document_only": (True, False), "structured_only": (False, True), "hybrid": (True, True)}
INLINE_TRACK = "hybrid_inline"


def _load_manifest(path: Path) -> dict:
    if sha256_file(path) not in SEC_MANIFEST_SHA256:
        raise ValueError("SEC corpus manifest differs from the frozen G2 input")
    return json.loads(path.read_bytes())


def _prepare_sec(manifest: dict, cache_dir: Path, output: Path, tickers: dict[str, int]) -> CompanyFactsReplay:
    cache = SourceCache(cache_dir, None)
    cutoff = manifest["cutoff"]
    receipts = {}
    for issuer in manifest["issuers"]:
        ticker = issuer["ticker"]
        if ticker not in tickers:
            continue
        expected = issuer["company_facts"]
        path, receipt = cache.source(expected["url"], MAX_METADATA_BYTES)
        if receipt != expected or int(issuer["cik"]) != tickers[ticker]:
            raise ValueError(f"Company Facts receipt or issuer differs for {ticker}")
        payload = json.loads(path.read_bytes())
        for taxonomy in payload["facts"].values():
            for concept in taxonomy.values():
                concept["units"] = {
                    unit: [row for row in rows if row.get("filed", "9999-12-31") <= cutoff]
                    for unit, rows in concept["units"].items()
                }
        cik = tickers[ticker]
        destination = output / f"CIK{cik:010d}.json"
        write_json_atomic(destination, payload)
        receipts[ticker] = {"cik": cik, "file": destination.name, "sha256": sha256_file(destination).removeprefix("sha256:"),
                            "source_url": expected["url"]}
    write_json_atomic(output / "manifest.json", {"latest_filed": cutoff, "issuers": receipts})
    return CompanyFactsReplay(output, tickers, latest_filed=cutoff)


def _check_pdf_cell(cell: StatementCell, text: str) -> None:
    # Preserve the column positions. The row label must match from the start of a line.
    label = r"\s+".join(map(re.escape, cell.row.split()))
    row = re.compile(rf"^\s*{label}\s+(?=\$?\s*\d)")
    matches = [re.findall(r"(?<!\d)\d[\d,]*", line[match.end():])
               for line in text.splitlines() if (match := row.match(line))]
    if (len(matches) != 1 or len(matches[0]) <= cell.column
            or int(matches[0][cell.column].replace(",", "")) != cell.millions_usd):
        raise ValueError(f"PDF cell differs from label: {cell.pdf.name} page {cell.page}, {cell.row}, {cell.period}")


def _eligible_sec_locators(cell: StatementCell, payload: dict, cutoff: str) -> tuple[str, ...]:
    if cell.sec_concept is None:
        return ()
    concept = payload["facts"].get("us-gaap", {}).get(cell.sec_concept, {})
    rows = concept.get("units", {}).get("USD", ())
    observations: dict[str, set[int]] = {}
    for row in rows:
        accession = row.get("accn")
        if (not accession or accession not in {cell.pdf.accession, cell.original_accession}
                or row.get("start") != cell.start or row.get("end") != cell.end
                or row.get("filed", "9999-12-31") > cutoff or row.get("form") not in {"10-K", "10-Q"}):
            continue
        observations.setdefault(accession, set()).add(row["val"])
    return tuple(f"sec:{accession}" for accession, values in sorted(observations.items())
                 if values == {cell.millions_usd * 1_000_000})


def _label_case(case: PilotCase, sec_locators: dict[StatementCell, tuple[str, ...]]) -> AblationCase:
    claims = tuple(
        GoldClaim(
            f"USD {cell.millions_usd:,} million", (cell.pdf.company, cell.metric),
            ((f"{cell.pdf.name}#p{cell.page}", *sec_locators[cell]),), (cell.period,),
        )
        for cell in case.cells
    )
    return AblationCase(case.case_id, "development", case.category, case.question, case.intended_path, claims)


def _label_narrative_case(case: NarrativeCase, pages: FrozenPdfPages) -> AblationCase:
    page = " ".join((pages.get(case.pdf.name, case.page) or "").split())
    if not case.excerpts or any(not excerpt or " ".join(excerpt.split()) not in page for excerpt in case.excerpts):
        raise ValueError(f"Narrative reference excerpt differs from {case.pdf.name} page {case.page}")
    claim = GoldClaim("", (), ((f"{case.pdf.name}#p{case.page}",),), statement=case.statement)
    return AblationCase(case.case_id, "development", "narrative", case.question, ExecutionPath.FAST, (claim,))


def _validate_track(track: str, observed: AblationObservation, statement_calls: int) -> None:
    use_pdf, use_sec = TRACKS["hybrid" if track == INLINE_TRACK else track]
    sources = observed.retrieved_sources.union(item for item in observed.citation_sources if item is not None)
    if track != INLINE_TRACK and any(s.startswith("ixbrl:") for s in sources):
        raise RuntimeError(f"{track} used an Inline XBRL source")
    if not use_pdf and (observed.retrieval_calls or statement_calls or any(not s.startswith("sec:") for s in sources)):
        raise RuntimeError(f"{track} used a PDF source")
    if not use_sec and (observed.sec_calls or any(s.startswith("sec:") for s in sources)):
        raise RuntimeError(f"{track} used a structured source")
    if observed.llm_calls:
        raise RuntimeError(f"{track} used a hosted generator")


def _run_track(
    track: str, cases: tuple[AblationCase, ...], router: ComplexityRouter, index: FrozenDenseRetriever,
    sec: CompanyFactsReplay, ticker_by_company: dict[str, str], *, inline_energy_fact: ResolvedCompanyFact | None = None,
) -> dict[str, Any]:
    use_pdf, use_sec = TRACKS["hybrid" if track == INLINE_TRACK else track]
    recorder = _RecordingRetriever(index)
    graph = SpecialistResearchGraph(router=router, retriever=recorder if use_pdf else None,
                                    sec_client=sec if use_sec else None, ticker_by_company=ticker_by_company,
                                    inline_energy_fact=inline_energy_fact)
    policy = _PolicyLayer(router.extractor)
    rows = []
    for case in cases:
        recorder.reset()
        before = sec.request_count
        start = time.perf_counter()
        result = graph.run(case.question, request_id=f"{track}-{case.case_id}")
        latency_ms = (time.perf_counter() - start) * 1_000
        observed = _specialist_observation(result, recorder, sec.request_count - before, policy)
        _validate_track(track, observed, recorder.statement_calls)
        row = evaluate_observation(case, observed, latency_ms=latency_ms, require_complete_claims=True)
        rows.append({**row, "citation_sources": observed.citation_sources,
                     "retrieved_sources": sorted(observed.retrieved_sources), "statement_calls": recorder.statement_calls,
                     "source_capability": result.route.source_capability})
    return {"overall": summarize_ablation(rows), "per_case": rows,
            "by_category": {category: summarize_ablation([row for row in rows if row["category"] == category])
                            for category in sorted({case.category for case in cases})}}


def _run_architecture_controls(
    cases: tuple[AblationCase, ...], router: ComplexityRouter, index: FrozenDenseRetriever,
    sec: CompanyFactsReplay, ticker_by_company: dict[str, str],
) -> dict:
    recorder = _RecordingRetriever(index)
    dense_policy = EvidenceDecisionLayer(extractor=router.extractor)
    graph = SpecialistResearchGraph(router=router, retriever=recorder, sec_client=sec,
                                    ticker_by_company=ticker_by_company)
    rows_by_arm = {"dense_a0": [], "adaptive": []}
    for name, rows in rows_by_arm.items():
        for case in cases:
            recorder.reset()
            started = time.perf_counter()
            if name == "dense_a0":
                observed = _solo("A0", case.question, recorder, dense_policy, None)
                details = {}
            else:
                route = router.route(case.question, force_research=True, source_inventory=graph.source_inventory)
                observed, details = _adaptive(case.question, route, graph, recorder, sec, f"{name}-{case.case_id}")
            if observed.llm_calls:
                raise RuntimeError(f"{name} used a hosted generator")
            row = evaluate_observation(case, observed, latency_ms=(time.perf_counter() - started) * 1_000,
                                       require_complete_claims=True, require_verified_release=name != "dense_a0")
            rows.append({**row, **details, "citation_sources": observed.citation_sources,
                         "retrieved_sources": sorted(observed.retrieved_sources)})
    return {name: {"overall": summarize_ablation(rows), "per_case": rows} for name, rows in rows_by_arm.items()}


def _load_pilot_vectors(
    directory: Path, *, chunks_hash: str, rows: int, dimension: int, report: dict | None = None,
):
    import numpy as np

    if report is None:
        report = json.loads((directory / "report.json").read_bytes())
    if report["chunks_sha256"] != chunks_hash or report["embedding_revision"] != P1_EMBEDDING_REVISION:
        raise ValueError("Frozen vectors do not match the reconstructed chunks and model")
    content = (directory / "normalized-vectors.npy").read_bytes()
    if report["vectors_sha256"] != f"sha256:{hashlib.sha256(content).hexdigest()}":
        raise ValueError("Frozen vector bytes differ from the pilot report")
    vectors = np.load(io.BytesIO(content), allow_pickle=False)
    if (vectors.shape != (rows, dimension) or vectors.dtype != np.float32
            or not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)):
        raise ValueError("Frozen vectors must have the expected shape, dtype and unit norms")
    return vectors


def _pdf_ranking_metrics(cases: tuple[PilotCase, ...], rankings: dict[str, tuple[str, ...]]) -> dict:
    adjudications = []
    for case in cases:
        targets = {f"cell_{i}": frozenset({f"{cell.pdf.name}#p{cell.page}"}) for i, cell in enumerate(case.cells)}
        relevant = frozenset(page for choices in targets.values() for page in choices)
        adjudications.append(RetrievalAdjudication(
            granularity="page", ranked_ids=rankings[case.case_id], relevant_ids=relevant, gold_targets=targets,
        ))
    metrics = score_retrieval(adjudications)["page"]
    return {
        "gold_locator_precision_at_10": metrics["context_precision_at_10"],
        "gold_evidence_recall_at_10": metrics["gold_evidence_recall_at_10"],
    }


def _run_ranking_controls(
    cases: tuple[PilotCase, ...], router: ComplexityRouter, dense: FrozenDenseRetriever, ranked: FrozenDenseRetriever,
) -> dict:
    import numpy as np

    answerable = tuple(case for case in cases if case.cells)
    methods = ("dense", "scoped_dense", "scoped_statement_rank")
    rows: dict[str, list[dict]] = {name: [] for name in methods}
    for i, case in enumerate(answerable):
        route = router.route(case.question)
        tasks = route.research_plan.tasks if route.research_plan else ()
        scope = tuple(sorted({doc for task in tasks for doc in task.target_document_ids}))
        # Rotate order to reduce bias from running one arm first on every query.
        offset = i % len(methods)
        for method in methods[offset:] + methods[:offset]:
            document_ids = scope if method != "dense" else ()
            index = ranked if method == "scoped_statement_rank" else dense
            started = time.perf_counter()
            retrieved = []
            if document_ids or method == "dense":
                retrieved = index.retrieve(case.question, top_k=10, document_ids=document_ids)
            latency_ms = (time.perf_counter() - started) * 1_000
            if document_ids and any(chunk["document_id"] not in document_ids for chunk in retrieved):
                raise RuntimeError(f"{method} returned an out-of-scope result for {case.case_id}")
            rows[method].append({
                "case_id": case.case_id, "document_scope": document_ids,
                "ranked_pages": tuple(f"{chunk['doc_name']}#p{chunk['page_number']}" for chunk in retrieved),
                "ranked_chunks": tuple(chunk["chunk_id"] for chunk in retrieved), "latency_ms": round(latency_ms, 3),
            })
    return {name: {
        **_pdf_ranking_metrics(answerable, {row["case_id"]: row["ranked_pages"] for row in records}),
        "p50_ms": round(float(np.percentile([row["latency_ms"] for row in records], 50)), 3),
        "p95_ms": round(float(np.percentile([row["latency_ms"] for row in records], 95)), 3),
        "per_case": records,
    } for name, records in rows.items()}


def _run(
    pdf_dir: Path, cache_dir: Path, manifest_path: Path, output: Path, threads: int, *,
    architecture_controls: bool = False, inline_facts: Path | None = None,
    ranking_controls: bool = False, reuse_pilot_vectors: Path | None = None, narrative_controls: bool = False,
) -> None:
    import numpy as np
    import torch

    from src.retrieval.embedder import Embedder

    start = time.perf_counter()
    torch.set_num_threads(threads)
    manifest = _load_manifest(manifest_path)
    filings = {row["accession_number"]: row for row in manifest["filings"]}
    chunks, all_pages, pdf_records = [], {}, []
    tickers, ticker_by_company = {}, {}
    for pdf in PDFS:
        filing = filings[pdf.accession]
        path = pdf_dir / f"{pdf.name}.pdf"
        if sha256_file(path) != f"sha256:{pdf.sha256}":
            raise ValueError(f"PDF hash differs: {pdf.name}")
        pages = extract_pdf_pages(path)
        all_pages[pdf.name] = pages
        document_chunks, stats = chunk_pdf_pages(pages, document_metadata={
            "doc_name": pdf.name, "company": pdf.company, "doc_type": filing["form_type"],
            "reporting_periods": [pdf.fiscal_year], "doc_link": pdf.url,
            "source_repository_url": filing["source_url"],
        })
        for chunk in document_chunks:
            chunk.update(ticker=filing["ticker"], cik=filing["cik"], accession=pdf.accession,
                         report_date=filing["report_date"])
        chunks.extend(document_chunks)
        pdf_records.append({**filing, **stats, "doc_name": pdf.name, "physical_pages": len(pages),
                            "pdf_url": pdf.url, "pdf_sha256": f"sha256:{pdf.sha256}"})
        tickers[filing["ticker"]] = filing["cik"]
        ticker_by_company[pdf.company.casefold()] = filing["ticker"]
    pages_path = output / "pages.jsonl"
    with pages_path.open("wb") as stream:
        for name, pages in all_pages.items():
            for page in pages:
                stream.write(canonical_json_bytes({"doc_name": name, **page}) + b"\n")
    pages_hash = sha256_file(pages_path)
    pages_cache = FrozenPdfPages(pages_path, expected_sha256=pages_hash)
    narrative_cases = tuple(_label_narrative_case(case, pages_cache) for case in NARRATIVE_CASES) if narrative_controls else ()
    narrative_reference = output / "narrative-reference.json"
    if narrative_cases:
        write_json_atomic(narrative_reference, {
            "status": STATUS, "label_source": "AUTHOR_CHECKED_PDF_DISCLOSURES", "pages_sha256": pages_hash,
            "cases": [asdict(case) for case in narrative_cases],
            "source_checks": [asdict(case) for case in NARRATIVE_CASES],
        })
    sec = _prepare_sec(manifest, cache_dir, output / "company-facts", tickers)
    sec_locators = {}
    for cell in dict.fromkeys(cell for case in CASES for cell in case.cells):
        page_text = pages_cache.get(cell.pdf.name, cell.page)
        if page_text is None:
            raise ValueError(f"Missing reference page for {cell.pdf.name}")
        _check_pdf_cell(cell, page_text)
        ticker = ticker_by_company[cell.pdf.company.casefold()]
        sec_locators[cell] = _eligible_sec_locators(cell, sec.facts[tickers[ticker]], manifest["cutoff"])
    cases = tuple(_label_case(case, sec_locators) for case in CASES)
    gold_path = output / "reference.json"
    write_json_atomic(gold_path, {"status": STATUS, "label_source": "PDF_TRANSCRIBED",
                                 "cases": [asdict(case) for case in cases]})
    print(f"Frozen {len(cases)} provisional questions: {sha256_file(gold_path)}", flush=True)
    chunks_hash = canonical_sha256(chunks)
    corpus = CorpusMap.from_chunks(chunks, index_generation_id=chunks_hash)
    router = ComplexityRouter(corpus)
    embedder = Embedder(device="cpu", revision=P1_EMBEDDING_REVISION)
    if reuse_pilot_vectors is None:
        print(f"Embedding {len(chunks)} chunks", flush=True)
        vectors = np.asarray(embedder.embed_documents([chunk["text"] for chunk in chunks], show_progress_bar=False),
                             dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if not np.all(np.isfinite(norms) & (norms > 0)):
            raise ValueError("Document embeddings must be finite and nonzero")
        vectors /= norms
    else:
        print(f"Reusing frozen vectors for {len(chunks)} chunks", flush=True)
        vectors = _load_pilot_vectors(reuse_pilot_vectors, chunks_hash=chunks_hash, rows=len(chunks), dimension=embedder.dimension)
    vector_path = output / "normalized-vectors.npy"
    np.save(vector_path, vectors, allow_pickle=False)
    index = FrozenDenseRetriever(chunks, vectors, embedder, pdf_pages=pages_cache,
                                 statement_ranker=FinancialStatementRanker(pages_cache, router.extractor))
    setup_ms = (time.perf_counter() - start) * 1_000
    results = {}
    for track in TRACKS:
        print(f"Running {track}", flush=True)
        results[track] = _run_track(track, cases, router, index, sec, ticker_by_company)
    inline_reference = None
    if inline_facts is not None:
        # Declare the fact locator separately. The PDF-transcribed gold stays frozen.
        locator = f"ixbrl:{ENERGY_IDENTITY.fact_id}"
        inline_cases = tuple(replace(case, claims=(replace(
            case.claims[0], source_slots=((*case.claims[0].source_slots[0], locator),),
        ),)) if case.case_id == "tesla_energy" else case for case in cases)
        accession = ENERGY_FILING.accession_number
        digest = filings[accession]["facts_sha256"]
        fact = load_energy_revenue(inline_facts / f"{accession}.json", digest)
        inline_reference = {"case_id": "tesla_energy", "locator": locator,
                            "source_url": fact.filing_url, "extraction_sha256": digest}
        print(f"Running {INLINE_TRACK}", flush=True)
        results[INLINE_TRACK] = _run_track(INLINE_TRACK, inline_cases, router, index, sec, ticker_by_company,
                                           inline_energy_fact=fact)
    report = {
        "schema": "filingscope.sec-runtime-pilot.v1", "status": STATUS, "label_source": "PDF_TRANSCRIBED",
        "scorer": "ablation_complete_claims_locator", "tracks": results,
        "categories": Counter(case.category for case in cases), "sec_manifest_sha256": sha256_file(manifest_path),
        "pdfs": pdf_records, "pages_sha256": pages_hash, "reference_sha256": sha256_file(gold_path),
        "company_facts": sec.manifest, "chunks": len(chunks), "chunks_sha256": chunks_hash,
        "embedding_model": embedder.model_name, "embedding_revision": embedder.model_revision,
        "vectors_sha256": sha256_file(vector_path), "threads": threads, "setup_ms": round(setup_ms, 3),
        "peak_memory_bytes": peak_memory_bytes(),
    }
    if architecture_controls:
        report["architecture_controls"] = _run_architecture_controls(cases, router, index, sec, ticker_by_company)
        report["peak_memory_bytes"] = peak_memory_bytes()
    if ranking_controls:
        dense = FrozenDenseRetriever(chunks, vectors, embedder, pdf_pages=pages_cache)
        report["ranking_controls"] = {
            "ranking_only": _run_ranking_controls(CASES, router, dense, index),
            "document_only_dense": _run_track("document_only", cases, router, dense, sec, ticker_by_company),
        }
        report["peak_memory_bytes"] = peak_memory_bytes()
    if narrative_cases:
        report["narrative_controls"] = {
            "reference_sha256": sha256_file(narrative_reference),
            "tracks": {track: _run_track(track, narrative_cases, router, index, sec, ticker_by_company) for track in TRACKS},
        }
        report["peak_memory_bytes"] = peak_memory_bytes()
    if inline_reference is not None:
        report["inline_reference"] = inline_reference
    write_json_atomic(output / "report.json", report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdfs", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=Path("docs/G2_SEC_CORPUS_MANIFEST.json"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threads", type=int, choices=range(1, 17), default=6)
    parser.add_argument("--architecture-controls", action="store_true")
    parser.add_argument("--ranking-controls", action="store_true", help="Compare Dense, document scope and statement ranking")
    parser.add_argument("--narrative-controls", action="store_true", help="Replay source-checked narrative questions separately")
    parser.add_argument("--reuse-pilot-vectors", type=Path, help="Use verified document vectors from a prior pilot run")
    parser.add_argument("--inline-facts", type=Path, help="Frozen G2 facts directory for the optional Inline XBRL arm")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with offline_socket_guard():
        _run(args.pdfs, args.cache, args.manifest, args.output, args.threads,
             architecture_controls=args.architecture_controls, inline_facts=args.inline_facts,
             ranking_controls=args.ranking_controls, reuse_pilot_vectors=args.reuse_pilot_vectors,
             narrative_controls=args.narrative_controls)


if __name__ == "__main__":
    main()
