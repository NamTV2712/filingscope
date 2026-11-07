# Corpus-aware planning

## Status

There is no runtime Corpus Map or corpus-conditioned planner today. Current
requirements are extracted from the user's question and evidence chunks;
FinanceBench benchmark labels are evaluation-only. M4 will add corpus
conditioning without exposing gold evidence or benchmark labels to runtime.

## Corpus Map contract

The planner should receive a compact view built from available runtime
metadata, for example company/CIK/ticker, form, filing year, document ID,
sections/items, table availability, XBRL coverage, and index generation. It
must distinguish `AVAILABLE`, `MISSING`, and `UNKNOWN` source states and must
not invent a local filing or XBRL fact path.

The map should not contain raw filing text, benchmark answers, gold page labels,
or expensive model-generated descriptions. A task should reference document
and evidence IDs rather than copied context.

## M4 experiment

- **Baseline:** query decomposition using question text and current requirement
  extraction only.
- **Treatment:** the same planner conditioned on a frozen runtime Corpus Map.
- **Dataset:** development questions with known corpus metadata; held-out
  comparisons stay frozen.
- **Measures:** task/requirement correctness, generated query candidate recall,
  nonexistent-source requests, company/period alignment, retrieval calls,
  latency, and token count.
- **Decision:** adopt only if the Corpus Map reduces invalid or missed
  retrieval with bounded overhead. Record failures where source state is
  missing or incomplete.
