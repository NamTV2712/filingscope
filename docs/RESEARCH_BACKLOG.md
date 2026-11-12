# Research backlog

Priority follows the prescribed M1–M15 order. “Done” describes implemented,
tested work only; design notes are not completion evidence.

| Priority | Work | Status / dependency | Completion evidence |
|---|---|---|---|
| M1 | Offline vertical retrieval → decision → adaptive retrieval → generation → verification | Complete in P5 evaluation harness | Reproducible 150-case run, tests, per-split results and failure analysis |
| M2 | Explain dense over hybrid with stage diagnostics | Complete | [150-case report](RETRIEVAL_DIAGNOSTICS_RESULTS.md): candidate recall, fusion/pool/filter/reranker metrics, split results, latency, resources, and provenance |
| M3 | Candidate Evidence Policy Engine and decision benchmark | Complete; synthetic behavior benchmark only | Versioned schema/policy, hard constraints, 60-case decision report and replay tests; see [M3 report](EVIDENCE_POLICY_EVALUATION.md) |
| M4 | Runtime Corpus Map and corpus-aware planning | Complete; standalone research component, not wired into P5 | [150-case report](CORPUS_AWARE_PLANNING.md): BM25 Recall@10 +4.34 pp overall and +2.22 pp held-out; 10/10 absent-company calls avoided; p95 latency trade-off recorded |
| M5 | Finite complexity/cost routing | Complete; standalone router, no workers invoked | [Routing report](COMPLEXITY_ROUTING.md): 56 authored fixtures, budget checks, and 150 unlabeled FinanceBench route distribution; downstream answer quality remains unmeasured |
| M6 | Shared Evidence Ledger | Complete; request-scoped in-memory blackboard | [Ledger report](EVIDENCE_LEDGER.md): stable IDs, atomic/idempotent merge and dedup, provenance links, financial facts, derived-fact inputs, claims and verification relations |
| M7 | Specialist research graph | Complete; sequential, bounded workflow | [Specialist graph report](SPECIALIST_RESEARCH_GRAPH.md): filing/table/XBRL/evidence/reasoner/writer/verifier contracts; 4-node FAST, 8-node RESEARCH, 1-node UNSUPPORTED paths; 20 focused tests, no answer-quality benchmark |
| M8 | Bounded parallel independent tasks | Complete | [M8 report](PARALLEL_RESEARCH.md) covers concurrency, budgets, duplicate work, failure isolation and a controlled latency comparison |
| M9 | SEC XBRL and fact normalization | Complete | [M9 fixture replay](FINANCIAL_FACT_ARCHITECTURE.md) covers CIK, concept, date interval, currency, provenance, amendments and changed comparatives |
| M10 | Docling and structure-aware parsing experiment | Complete. pypdf remains the default | [Five-PDF comparison](DOCUMENT_INTELLIGENCE.md) with fidelity, retrieval, time, RAM and disk measurements |
| M11 | Atomic claims and bounded correction | Complete in the specialist graph | [M11 replay](ADVANCED_VERIFICATION.md) covers claim statuses, evidence links and one-pass correction |
| M12 | Provenance-sensitive hard negatives | Complete | [24-case benchmark](HARD_NEGATIVE_RETRIEVAL.md) includes five provenance confusions and full-corpus rankings |
| M13 | Multi-agent and router ablation | Complete | [A0–A4 and B0–B5](ABLATION_STUDY.md) compared on quality, provenance, calls and latency |
| M14 | ColBERT, multivectors and graph retrieval adaptations | Complete. Dense stays the default | [R6 and fixed-pool comparisons](ADVANCED_RETRIEVAL.md) |
| M15 | Local evidence-first research UX | After API/ledger contracts | inspectable answer/sources/coverage/calculation/verification/trace flow |

Cloud deployment is not on this backlog. No work may expand the agent graph
without a defined capability, finite budget, reproducible test, and ablation.
