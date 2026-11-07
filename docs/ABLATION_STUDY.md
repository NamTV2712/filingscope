# A0–A5 ablation study

All six variants use the same 150 cases, pinned P1 corpus, and frozen answer prompt. Each row adds one component to the preceding variant. A5 reuses A4 answers and applies the claim verifier as an output gate.

Quality and latency columns below use the held-out split. Calls and modeled cost columns count responses used by the completed benchmark run; they exclude any abandoned provider attempts listed in the results header.

| Variant | Enabled component | Coverage | Text token F1 | Numeric exact | Citation validity | p95 ms | Calls | Cost USD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A0 | Dense retrieval + generator | 44.4% | 11.6% | 0.0% | 100.0% | 7751.3 | 150 | $0.12828405 |
| A1 | Hybrid retrieval + generator | 35.6% | 16.4% | 0.0% | 85.2% | 10798.4 | 150 | $0.12559665 |
| A2 | Hybrid retrieval + reranker + generator | 40.0% | 17.9% | 0.0% | 100.0% | 7803.7 | 150 | $0.09421350 |
| A3 | A2 + evidence decision | 0.0% | 7.4% | 0.0% | n/a | 2487.9 | 5 | $0.00344670 |
| A4 | A3 + adaptive retrieval | 0.0% | 7.4% | 0.0% | n/a | 4067.4 | 5 | $0.00344610 |
| A5 | A4 + claim verification gate | 0.0% | 7.4% | 0.0% | n/a | 4067.4 | 0 | $0 |

| Transition | Change in answer token F1 | Change in coverage | Change in numeric exact accuracy |
|---|---:|---:|---:|
| A0 → A1 | +4.8 pp | -8.9 pp | +0.0 pp |
| A1 → A2 | +1.5 pp | +4.4 pp | +0.0 pp |
| A2 → A3 | -10.6 pp | -40.0 pp | +0.0 pp |
| A3 → A4 | +0.0 pp | +0.0 pp | +0.0 pp |
| A4 → A5 | +0.0 pp | +0.0 pp | +0.0 pp |

These differences are descriptive for this pinned public sample. They are not a significance test. Text metrics are lexical agreement measures, and the evidence-page abstention proxy can misclassify cases where alternate evidence pages support the answer.
