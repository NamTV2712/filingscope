"""Run a public FinRank slice on complete filing PDFs with a two-step score."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from pydantic import TypeAdapter

from configs.offline_guard import offline_socket_guard
from scripts.prepare_independent_corpus import FilingInput
from scripts.run_independent_final import predict_filing_questions
from src.evaluation.answer_metrics import score_numeric_answer, score_text_answer
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.independent_final import ARMS, Corpus, Question, read_pinned
from src.generation.answer_generator import is_fallback_answer
from src.retrieval.canonical_json import canonical_sha256, sha256_file


REVISION = "916dc27e77b90e294ea1b3a2cc5b0abcf07392d1"
DATA_SHA256 = "sha256:e9295f680bd6085362486c90c170bce243be7f85ed18074d6ba21cb75141ac78"
URL = f"https://github.com/datanxt/FinRank/tree/{REVISION}"


def _cases(data: Path, filings: dict[str, FilingInput], year: int):
    for line in read_pinned(data, DATA_SHA256).splitlines():
        item = json.loads(line)
        if item["ticker"] in filings and item["year"] == year and item["doc_type"] == "10-K":
            yield item


def _normalize(text: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _gold_pages(passages: list[dict], pages: dict[int, str], document: str) -> tuple[str, ...] | None:
    """Map publisher passages onto physical pages by unique exact text."""
    mapped = set()
    for passage in passages:
        fragment = _normalize(passage["text"])
        hits = [number for number, text in pages.items() if len(fragment) >= 40 and fragment in text]
        if len(hits) != 1:
            return None
        mapped.add(f"{document}#p{hits[0]}")
    return tuple(sorted(mapped)) if mapped else None


def score(items: list[dict], predictions: dict, filings: dict[str, FilingInput], pages: dict) -> dict:
    if set(predictions) != set(ARMS) or any(set(rows) != {item["id"] for item in items} for rows in predictions.values()):
        raise ValueError("Prediction coverage differs from the fixed FinRank slice")
    outcomes = {arm: [] for arm in ARMS}
    for item in items:
        document = filings[item["ticker"]].document_id
        gold_pages = _gold_pages(item["passages"], pages[document], document)
        for arm in ARMS:
            row = predictions[arm][item["id"]]
            answer = row["answer"]
            released = bool(answer.strip()) and not is_fallback_answer(answer) and row["disposition"] in {"VERIFIED", "PARTIAL"}
            cited = {row["citation_sources"][int(i) - 1] for i in re.findall(r"\[Source ([1-9]\d*)\]", answer)
                     if int(i) <= len(row["citation_sources"])}
            numeric = score_numeric_answer(answer, item["answer"]) if item["reasoning_type"] == "Quantitative" else None
            text = score_text_answer(answer, item["answer"])
            complete_citations = bool(gold_pages and set(gold_pages) <= cited)
            outcomes[arm].append({"id": item["id"], "ticker": item["ticker"], "difficulty": item["difficulty"],
                                  "reasoning_type": item["reasoning_type"], "released": released,
                                  "disposition": row["disposition"], "numeric_exact": numeric and numeric["exact_match"],
                                  "text_exact": text["exact_match"], "text_f1": text["f1"], "gold_pages": gold_pages,
                                  "all_gold_pages_retrieved": set(gold_pages) <= set(row["retrieved_sources"]) if gold_pages else None,
                                  "all_gold_pages_cited": complete_citations if gold_pages else None,
                                  "numeric_exact_with_all_gold_pages": bool(released and numeric and numeric["exact_match"]
                                                                            and complete_citations) if gold_pages and numeric and numeric["scored"] else None,
                                  "tool_calls": row["tool_calls"], "llm_calls": row["llm_calls"], "latency_ms": row["latency_ms"]})

    def summary(rows):
        aligned = [row for row in rows if row["gold_pages"]]
        numeric = [row for row in rows if row["numeric_exact"] is not None]
        ordered = sorted(row["latency_ms"] for row in rows)
        grounded_numeric = [row for row in rows if row["numeric_exact_with_all_gold_pages"] is not None]
        return {"cases": len(rows), "released": sum(row["released"] for row in rows),
                "dispositions": dict(Counter(row["disposition"] for row in rows)),
                "quantitative_parseable": len(numeric), "numeric_exact": sum(row["numeric_exact"] for row in numeric),
                "text_exact": sum(row["text_exact"] for row in rows),
                "evidence_aligned": len(aligned),
                "all_gold_pages_retrieved": sum(row["all_gold_pages_retrieved"] for row in aligned),
                "all_gold_pages_cited": sum(row["all_gold_pages_cited"] for row in aligned),
                "aligned_numeric_cases": len(grounded_numeric),
                "numeric_exact_with_all_gold_pages": sum(row["numeric_exact_with_all_gold_pages"] for row in grounded_numeric),
                "median_latency_ms": median(ordered), "tool_calls": sum(row["tool_calls"] for row in rows),
                "llm_calls": sum(row["llm_calls"] for row in rows)}

    return {arm: {"overall": summary(rows), "by_issuer": {ticker: summary([row for row in rows if row["ticker"] == ticker])
                                                           for ticker in sorted(filings)},
                  "by_reasoning_type": {kind: summary([row for row in rows if row["reasoning_type"] == kind])
                                        for kind in sorted({row["reasoning_type"] for row in rows})}, "per_case": rows}
            for arm, rows in outcomes.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("predict", "score"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--filing-year", type=int, required=True)
    parser.add_argument("--threads", type=int, default=6, choices=range(1, 17))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--predictions-sha256")
    args = parser.parse_args()
    if args.mode == "score" and (args.predictions is None or not args.predictions_sha256):
        parser.error("Supply the recorded prediction file and hash for scoring")
    output = args.output.resolve()
    repo = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    if output.exists() or not output.is_relative_to(repo / "data"):
        parser.error("Use a new output file under the ignored data directory")

    with offline_socket_guard():
        bundle = args.bundle
        corpus = Corpus.model_validate_json((bundle / "corpus.json").read_bytes())
        inventory = TypeAdapter(list[FilingInput]).validate_json((bundle / "filing-inventory.json").read_bytes())
        filings = {row.ticker: row for row in inventory}
        if (not all(filings) or len(filings) != len(inventory)
                or any(row.filed.year != args.filing_year or row.form != "10-K" for row in inventory)
                or {row.document_id: row.document_sha256 for row in inventory} != {
                    row.document_id: row.document_sha256 for row in corpus.filings
                }):
            raise ValueError("Supply one verified 10-K per ticker and match the fixed corpus")
        configuration = {"dataset": URL, "dataset_sha256": DATA_SHA256, "license": "CC BY-NC 4.0",
                         "corpus_sha256": sha256_file(bundle / "corpus.json"),
                         "inventory_sha256": sha256_file(bundle / "filing-inventory.json"),
                         "filing_year": args.filing_year, "cutoff": args.cutoff,
                         "runner_sha256": sha256_file(Path(__file__)), "threads": args.threads,
                         "question_context": "issuer, ticker, form and fiscal year from the verified filing inventory"}
        items = _cases(args.dataset, filings, args.filing_year)
        if args.mode == "predict":
            questions = []
            for item in items:
                filing = filings[item["ticker"]]
                context = f"Filing context: {filing.company} ({filing.ticker}), Form 10-K for FY{filing.fiscal_year}."
                questions.append(Question(case_id=item["id"], category=item["reasoning_type"],
                                          question=f"{item['question']} {context}", issuer_ciks=(filing.cik,)))
            questions.sort(key=lambda item: item.case_id)
            if not questions:
                raise ValueError("The frozen selection returned no questions")
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            report = predict_filing_questions(bundle, corpus, questions, git_sha=sha, cutoff=args.cutoff, threads=args.threads)
            report["tracked_diff_sha256"] = canonical_sha256(subprocess.check_output(["git", "diff", "--binary", "HEAD"], text=True))
        else:
            saved = json.loads(read_pinned(args.predictions, args.predictions_sha256))
            if saved["configuration"] != configuration:
                raise ValueError("Prediction configuration differs from scoring inputs")
            pages = defaultdict(dict)
            for line in read_pinned(bundle / "pages.jsonl", corpus.pages_sha256).splitlines():
                page = json.loads(line)
                pages[page["doc_name"]][page["page_number"]] = _normalize(page["text"])
            report = {"results": score(list(items), saved["predictions"], filings, pages),
                      "predictions_sha256": args.predictions_sha256,
                      "runtime": {key: value for key, value in saved.items() if key not in {"predictions", "configuration"}}}
            print(json.dumps({arm: row["overall"] for arm, row in report["results"].items()}, indent=2))
        report["configuration"] = configuration
        write_json_atomic(output, report)
        print(sha256_file(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
