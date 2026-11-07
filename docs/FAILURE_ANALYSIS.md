# Failure analysis

This report groups the observed retrieval, generation, claim, and citation outcomes from the held run. It uses case identifiers and verifier reason codes; it does not publish FinanceBench gold answers.

The completed results followed an interrupted prior provider run with 61 attempts. Its case responses and token-usage details were not retained. The combined cost estimate carries its conservative upper bound of $0.08507790; per-case quality metrics use only responses from the completed run.

## Observed A4 verifier dispositions

- `ABSTAIN`: 2
- `PARTIAL`: 2
- `REJECTED`: 1

## Claim status counts

- `PARTIALLY_SUPPORTED`: 3
- `SUPPORTED`: 3
- `UNSUPPORTED`: 1
- `UNVERIFIABLE`: 12

## Frequent verifier reasons

- `missing_citation`: 8
- `evidence_value_not_parseable`: 5
- `some_topical_anchors_match_cited_text`: 3
- `topical_anchors_match_cited_text`: 3
- `fallback_answer`: 2
- `partially_supported_claim`: 1
- `unsupported_claim`: 1
- `cited_evidence_does_not_contain_claimed_fact`: 1
- `unverifiable_claim`: 1

## A5 verifier abstentions (150 cases)

- `financebench_id_00070`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00283`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00302`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00382`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00407`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00476`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00499`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00552`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00684`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00702`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00705`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00720`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00723`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00724`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00735`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00799`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00807`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00882`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_00941`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_01009`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_01028`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_01079`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_01148`: disposition `PARTIAL`, reasons `partially_supported_claim`, text exact `False`.
- `financebench_id_01163`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_01226`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_01254`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_01328`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_01351`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_01474`: disposition `ABSTAIN`, reasons `none`, text exact `False`.
- `financebench_id_01476`: disposition `ABSTAIN`, reasons `none`, text exact `False`.

## A4 numeric exact-match misses (0 answered cases)


## Incomplete annotated-page coverage (107 cases)

- `financebench_id_00070`: `unsupported_question`, decision `metric_not_recognized`, coverage `50.0%`.
- `financebench_id_00283`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_00302`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_00382`: `unsupported_question`, decision `company_not_resolved`, coverage `0.0%`.
- `financebench_id_00476`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_00499`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_00552`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_00684`: `no_progress`, decision `incomplete_evidence_after_budget`, coverage `0.0%`.
- `financebench_id_00702`: `unsupported_question`, decision `insufficient_period_scope`, coverage `0.0%`.
- `financebench_id_00720`: `no_progress`, decision `incomplete_evidence_after_budget`, coverage `0.0%`.
- `financebench_id_00723`: `unsupported_question`, decision `company_not_resolved`, coverage `0.0%`.
- `financebench_id_00724`: `no_progress`, decision `conflicting_evidence_after_budget`, coverage `0.0%`.
- `financebench_id_00735`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_00799`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_00807`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_00941`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_01009`: `unsupported_question`, decision `metric_not_recognized`, coverage `50.0%`.
- `financebench_id_01028`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_01079`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_01226`: `no_progress`, decision `incomplete_evidence_after_budget`, coverage `0.0%`.
- `financebench_id_01254`: `no_progress`, decision `conflicting_evidence_after_budget`, coverage `0.0%`.
- `financebench_id_01328`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_01351`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_01858`: `no_progress`, decision `conflicting_evidence_after_budget`, coverage `0.0%`.
- `financebench_id_01865`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_01911`: `unsupported_question`, decision `company_not_resolved`, coverage `0.0%`.
- `financebench_id_01912`: `unsupported_question`, decision `company_not_resolved`, coverage `0.0%`.
- `financebench_id_01928`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.
- `financebench_id_01930`: `no_progress`, decision `conflicting_evidence_after_budget`, coverage `0.0%`.
- `financebench_id_01936`: `unsupported_question`, decision `metric_not_recognized`, coverage `0.0%`.

Per-case generated answers and the full evidence audit trail remain in local ignored artifacts. Failure categories should be interpreted with the metric limitations in `BENCHMARK_RESULTS.md`.
