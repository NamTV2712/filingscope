"""Compare the Q6 writer and fixed-draft provider paths without network access."""

from __future__ import annotations

import argparse
import json
import re
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from configs.financebench import P1_INDEX_ID, P1_PAGE_CACHE, P1_RUN
from configs.offline_guard import offline_socket_guard
from configs.retrieval_utility import CASES, ISSUERS
from scripts.run_evidence_policy_validation import FixedCandidates
from scripts.run_multi_agent_ablation import _ledger_key
from src.agent.complexity_router import ComplexityRouter, CorpusMap
from src.agent.specialist_graph import SpecialistResearchGraph
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.multi_agent_ablation import AblationObservation, evaluate_observation, paired_grounded_exact, summarize_ablation
from src.evaluation.post_m15_manifest import build_manifest
from src.generation.answer_generator import GroqAnswerGenerator, estimate_prompt_tokens
from src.generation.grounded_writer import ProviderLimits
from src.retrieval.canonical_json import sha256_file
from src.retrieval.frozen_artifacts import load_frozen_corpus
from src.retrieval.pdf_page_cache import FrozenPdfPages
from src.verification.claim_verifier import ClaimLevelVerifier
from src.verification.models import ResponseDisposition
from src.verification.response_policy import INSUFFICIENT_EVIDENCE_ANSWER


RUNS = Path("data/financebench/ablation_runs")
P5_ARCHIVE = Path("data/financebench/e2e_runs/20261107T151230Z-beed7a9d26ee/results.json")
P5_SHA256 = "sha256:029556e1e6658c727ba36344b2f6bb6c5c6b77ebc415a2e7d5b44516c72daf0b"
MOCK_REPLIES = {
    "adobe_sales": ("paraphrase", "VERIFIED"),
    "costco_assets": ("paraphrase", "VERIFIED"),
    "mmm_quarter_revenue": ("paraphrase", "VERIFIED"),
    "paypal_sales": ("unapproved_same_page_metric", "PARTIAL"),
    "block_operating_loss": ("wrong_sign", "REJECTED"),
    "water_income": ("missing_citation", "ABSTAIN"),
    "kraft_currency_mismatch": ("wrong_currency", "ABSTAIN"),
}


class FixedDraftClient:
    """A Groq-compatible transport double with a predeclared reply per case."""

    def __init__(self, case, behavior):
        self.case, self.behavior = case, behavior
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.prompt = ""
        self.calls = 0

    def create(self, *, messages, **kwargs):
        self.calls += 1
        self.prompt = messages[1]["content"]
        index = {f"{document}#p{int(page) - 1}": int(number) for number, document, page in re.findall(
            r"^\[Source (\d+)\] ([^\n,]+), PDF page (\d+)$", self.prompt, re.M,
        )}
        if self.behavior == "wrong_currency":
            draft = "Kraft Heinz FY2019 operating income was EUR 3,070 million [Source 1]."
        else:
            claim, = self.case.claims
            company, metric = claim.terms
            period, = claim.periods
            locator = claim.source_slots[0][0]
            value = claim.value.replace("-", "") if self.behavior == "wrong_sign" else claim.value
            citation = "" if self.behavior == "missing_citation" else f" [Source {index[locator]}]"
            draft = f"{company}'s {period} {metric} was {value}{citation}."
            if self.behavior == "unapproved_same_page_metric":
                draft += f" PayPal's FY2022 operating income was USD 3,837 million [Source {index[locator]}]."
        return SimpleNamespace(
            id="fixture-response", choices=[SimpleNamespace(message=SimpleNamespace(content=draft))],
            usage=SimpleNamespace(prompt_tokens=estimate_prompt_tokens(messages), completion_tokens=40),
        )


def _reader(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sources(case):
    return tuple(dict.fromkeys(source for claim in case.claims for group in claim.source_slots for source in group))


def _mock_replay(chunks, router, pages):
    page_chunks = {(row["doc_name"], row["page_number"]): row for row in reversed(chunks)}
    variants = {name: [] for name in ("p5_mock_draft", "p5_mock_verified", "deterministic", "unified_mock")}
    for case in CASES:
        if case.case_id not in MOCK_REPLIES:
            continue
        behavior, expected = MOCK_REPLIES[case.case_id]
        locators = _sources(case) or ("KRAFTHEINZ_2019_10K#p49",)
        selected = tuple(page_chunks[document, int(page)] for document, page in (locator.rsplit("#p", 1) for locator in locators))
        old_client = FixedDraftClient(case, behavior)
        started = time.perf_counter()
        draft = GroqAnswerGenerator(api_key="fixture", client=old_client, max_output_tokens=100).generate(case.question, selected)
        verification = ClaimLevelVerifier(catalog=router.extractor.catalog).verify(case.question, draft.answer, selected)
        elapsed = (time.perf_counter() - started) * 1000
        verified = verification.disposition == ResponseDisposition.VERIFIED
        for name, answer, disposition in (
            ("p5_mock_draft", draft.answer, "DRAFT"),
            ("p5_mock_verified", draft.answer if verified else INSUFFICIENT_EVIDENCE_ANSWER, verification.disposition.value),
        ):
            row = evaluate_observation(case, AblationObservation(
                answer=answer, disposition=disposition, citation_sources=locators, retrieved_sources=frozenset(locators),
                input_tokens=draft.prompt_tokens or 0, output_tokens=draft.completion_tokens or 0, llm_calls=1,
            ), latency_ms=elapsed)
            variants[name].append(row)
        new_client = FixedDraftClient(case, behavior)
        for name in ("deterministic", "unified_mock"):
            optional = name == "unified_mock"
            graph = SpecialistResearchGraph(
                router=router, retriever=FixedCandidates(selected, pages),
                generator=GroqAnswerGenerator(api_key="fixture", client=new_client, max_output_tokens=100) if optional else None,
                provider_limits=ProviderLimits(max_calls=1, max_input_tokens=10_000, max_output_tokens=100,
                                               max_cost_usd=Decimal("0.01")) if optional else None,
            )
            started = time.perf_counter()
            result = graph.run(case.question, request_id=f"q6-{name}-{case.case_id}", force_research=True)
            elapsed = (time.perf_counter() - started) * 1000
            records = {record.evidence_id: record for record in result.ledger_snapshot.evidence_records}
            row = evaluate_observation(case, AblationObservation(
                answer=result.answer, disposition=result.status,
                citation_sources=tuple(_ledger_key(records[key]) for key in result.citation_evidence_ids),
                retrieved_sources=frozenset(locators), input_tokens=result.usage.input_tokens or 0,
                output_tokens=result.usage.output_tokens or 0, llm_calls=result.usage.llm_calls,
                correction_passes=result.usage.correction_passes,
            ), latency_ms=elapsed)
            row["expected_disposition"] = expected if optional else "VERIFIED" if case.claims else "ABSTAIN"
            row["transport_attempts"] = new_client.calls if optional else 0
            row["source_claim_count"] = len(result.citation_evidence_ids)
            row["claim_types"] = [claim.claim_type for claim in result.verification.claims] if result.verification else []
            row["outside_fact_visible_to_provider"] = optional and behavior == "unapproved_same_page_metric" and "3,837" in new_client.prompt
            variants[name].append(row)
    return {name: {"metrics": summarize_ablation(rows), "per_case": rows} for name, rows in variants.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=RUNS / "q5-utility-natural-runtime.json")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--api", type=Path, default=RUNS / "q6-writer-api.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    with offline_socket_guard():
        chunks = load_frozen_corpus(P1_RUN)
        router = ComplexityRouter(CorpusMap.from_chunks(chunks, index_generation_id=P1_INDEX_ID))
        mock = _mock_replay(chunks, router, FrozenPdfPages.from_run(P1_PAGE_CACHE, P1_RUN))
    before = _reader(args.baseline)["variants"]["natural_runtime"]
    after = _reader(args.candidate)["variants"]["natural_runtime"]
    pair = paired_grounded_exact(after["e2e_per_case"], before["e2e_per_case"], ISSUERS, seed=20261112)
    if sha256_file(P5_ARCHIVE) != P5_SHA256:
        raise ValueError("Historical P5 results differ from the frozen report")
    historical = _reader(P5_ARCHIVE)
    checked = mock["unified_mock"]["per_case"] + mock["deterministic"]["per_case"]
    gates = {
        "real_grounded_exact_no_regression": all(row["difference"] > 0 for row in pair["changed_cases"]),
        "real_no_unsupported_release": not after["e2e"]["unsupported_releases"],
        "mock_release_gate_matches_labels": all(row["disposition"] == row["expected_disposition"] for row in checked),
        "mock_no_unapproved_release": not any(row["unsupported_released_claims"] or row["outside_fact_visible_to_provider"] for row in checked),
        "single_bounded_correction": all(row["correction_passes"] <= 1 for row in checked),
        "no_hosted_quality_run": True,
    }
    safety = {}
    for key in ("m13_safety", "direct_safety"):
        old_rows, new_rows = before[key]["per_case"], after[key]["per_case"]
        assert [row["case_id"] for row in old_rows] == [row["case_id"] for row in new_rows]
        safety[key] = {"before": before[key]["summary"], "after": after[key]["summary"]}
        gates[key] = all(not new["unsupported_released_claims"] and (new["grounded_exact"] or not old["grounded_exact"])
                         for old, new in zip(old_rows, new_rows, strict=True))
    artifacts = {"baseline": args.baseline, "candidate": args.candidate, "p5": P5_ARCHIVE, "report": args.output}
    smoke = _reader(args.api)["statement"] if args.api.is_file() else None
    if smoke is not None:
        gates["loopback_numeric_and_abstention"] = len(smoke["cases"]) == 6 and all(
            row["grounded_exact"] and row["unsupported_released_claims"] == row["llm_calls"] == 0 for row in smoke["cases"])
        artifacts["loopback_smoke"] = args.api
    report = {
        "configuration": {"providers": [], "hosted_answer_quality": "NOT RUN", "seed": 20261112},
        "historical_p5": {"cases": historical["case_count"], "generator": historical["generator"],
                          "a4": historical["variants"]["A4"], "a5": historical["variants"]["A5"]},
        "real": {"before": before["e2e"], "after": after["e2e"], "by_split": after["e2e_by_split"], "paired": pair},
        "safety": safety, "mock": mock, "loopback_smoke": smoke, "gates": gates,
    }
    write_json_atomic(args.output, report)
    write_json_atomic(args.manifest, build_manifest(
        p1_run=P1_RUN, source_manifest=Path("data/financebench/source_manifest.json"), sec_manifest=RUNS / "m13-sec/manifest.json",
        pages=P1_PAGE_CACHE, artifacts=artifacts,
        configuration=report["configuration"], code_files=(
            "scripts/run_grounded_writer_evaluation.py", "src/generation/grounded_writer.py", "src/generation/answer_generator.py",
            "src/agent/specialist_graph.py", "src/agent/specialists.py", "src/decision/evidence_coverage.py",
            "src/decision/period_value_parser.py", "src/verification/atomic_claim_verifier.py", "src/verification/claim_verifier.py",
            "src/verification/models.py", "scripts/run_local_research.py",
        ),
    ))
    print(gates)
    if not all(gates.values()):
        raise SystemExit("A Q6 writer comparison gate failed")


if __name__ == "__main__":
    main()
