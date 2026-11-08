# Research backlog

Priority follows the prescribed M1–M15 order. “Done” describes implemented,
tested work only; design notes are not completion evidence.

| Priority | Work | Status / dependency | Completion evidence |
|---|---|---|---|
| M1 | Offline vertical retrieval → decision → adaptive retrieval → generation → verification | Complete in P5 evaluation harness | Reproducible 150-case run, tests, per-split results and failure analysis |
| M2 | Explain dense over hybrid with stage diagnostics | Complete | [150-case report](RETRIEVAL_DIAGNOSTICS_RESULTS.md): candidate recall, fusion/pool/filter/reranker metrics, split results, latency, resources, and provenance |
| M3 | Candidate Evidence Policy Engine and decision benchmark | Complete; synthetic behavior benchmark only | Versioned schema/policy, hard constraints, 60-case decision report and replay tests; see [M3 report](EVIDENCE_POLICY_EVALUATION.md) |
| M4 | Runtime Corpus Map and corpus-aware planning | Next | Query-only vs map-conditioned study; no benchmark label leakage |
| M5 | Finite complexity/cost routing | After M4 | Router correctness, unnecessary research rate, quality/cost/latency study |
| M6 | Shared Evidence Ledger | After policy and planning contracts | Stable IDs, deterministic merge/dedup, provenance and derived-fact tests |
| M7 | Specialist capabilities | After ledger | Filing/table/evidence/reasoner interfaces; XBRL research can proceed in M9 |
| M8 | Bounded parallel independent tasks | After sequential graph works | Concurrency, budget, duplicate work and failure isolation tests |
| M9 | SEC XBRL and fact normalization | Can be researched with M7 | Company/tag/period/unit/accession/amendment fixture coverage |
| M10 | Docling and structure-aware parsing experiment | After failure subset selection | pypdf comparison with fidelity, retrieval, time, RAM, disk measurements |
| M11 | Atomic claims and bounded correction | After ledger | claim/evidence/calculation graph, verifier benchmark, one bounded correction |
| M12 | Provenance-sensitive hard negatives | Seed from M2 diagnostic misses | Frozen company/year/context-confusable test cohort |
| M13 | Multi-agent and router ablation | After M5–M9 | B0–B5 compared on quality, provenance, cost, calls and latency |
| M14 | ColBERT/multivectors/GraphRAG/HippoRAG/LightRAG | Only after R1–R6 | Retain only measured improvements against dense baseline |
| M15 | Local evidence-first research UX | After API/ledger contracts | inspectable answer/sources/coverage/calculation/verification/trace flow |

Cloud deployment is not on this backlog. No work may expand the agent graph
without a defined capability, finite budget, reproducible test, and ablation.
