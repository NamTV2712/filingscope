"""Evaluate parser fidelity and dense retrieval on the frozen M10 cohort."""

from __future__ import annotations

import argparse
import json
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from configs.document_intelligence import CASE_IDS, DOCUMENTS, READING_ORDER, TABLE_ROWS
from src.evaluation.financebench_dataset import (
    evidence_alignment_stats,
    load_financebench_cases,
    normalize_document_metadata,
)
from src.evaluation.retrieval_metrics import evaluate_retrieval
from src.ingestion.pdf_ingestion import chunk_pdf_pages
from src.ingestion.structured_pdf_chunks import chunk_docling_pages, column_headers


NOMIC_REVISION = "e9b6763023c676ca8431644204f50c2b100d9aab"
_DIGITS = r"\d[\d,]*(?:\.\d+)?"
_NUMBER = re.compile(rf"(?:\$?\s*\(\s*\$?\s*{_DIGITS}\s*\)|-?\$?\s*{_DIGITS})")


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def _ordered(text: str, anchors: tuple[str, ...]) -> bool:
    text = _normalized(text)
    cursor = 0
    for anchor in anchors:
        match = re.search(rf"\b{re.escape(_normalized(anchor))}\b", text[cursor:])
        if match is None:
            return False
        cursor += match.end()
    return True


def _number(text: str) -> Decimal:
    value = re.sub(r"[\s$,]", "", text)
    if value.startswith("(") and value.endswith(")"):
        value = f"-{value[1:-1]}"
    return Decimal(value)


def _label_regex(label: str) -> re.Pattern:
    parts = [re.escape(word) for word in _normalized(label).split()]
    return re.compile(r"\b" + r"[^\w]+".join(parts) + r"\b", re.I)


def _text_row(text: str, label: re.Pattern, values: tuple[Decimal, ...]) -> bool:
    for line in text.splitlines():
        match = label.search(line)
        if match:
            numbers = tuple(_number(number.group()) for number in _NUMBER.finditer(line[match.end():]))
            if numbers == values:
                return True
    return False


def _native_row(
    page: dict[str, Any], label: re.Pattern, values: tuple[Decimal, ...],
    expected_headers: tuple[tuple[str, ...], ...],
) -> tuple[bool, bool, int]:
    table_found = False
    best_headers = 0
    row_found = False
    for block in page.get("blocks", []):
        if block["kind"] != "table":
            continue
        cells = block["cells"]
        for label_cell in cells:
            if not label.search(label_cell["text"]):
                continue
            row = label_cell["row_start"]
            numeric_cells = sorted(
                (cell for cell in cells if cell["row_start"] == row
                 and cell["column_start"] >= label_cell["column_end"]
                 and _NUMBER.fullmatch(cell["text"].strip())),
                key=lambda cell: cell["column_start"],
            )
            observed = tuple(_number(cell["text"]) for cell in numeric_cells)
            table_found |= len(set(observed) & set(values)) >= 2
            if observed != values:
                continue
            row_found = True
            count = sum(
                _ordered(" ".join(column_headers(cells, row, cell["column_start"])), headers)
                for cell, headers in zip(numeric_cells, expected_headers, strict=True)
            )
            best_headers = max(best_headers, count)
    return table_found, row_found, best_headers


def audit_pages(parses: dict[str, Any]) -> dict[str, int]:
    pages = {
        (document, page["page_number"]): page
        for document, parse in parses.items() for page in parse["pages"]
    }
    reading = sum(_ordered(pages[key]["text"], anchors) for key, anchors in READING_ORDER.items())
    text_rows = tables = rows = headers = 0
    for document, page_index, label, amounts, expected_headers in TABLE_ROWS:
        page = pages[(document, page_index)]
        pattern = _label_regex(label)
        values = tuple(Decimal(amount) for amount in amounts)
        text_rows += _text_row(page["text"], pattern, values)
        table_found, row_found, header_count = _native_row(page, pattern, values, expected_headers)
        tables += table_found
        rows += row_found
        headers += header_count
    return {
        "reading_order_matches": reading,
        "reading_order_checks": len(READING_ORDER),
        "text_row_matches": text_rows,
        "native_table_matches": tables,
        "native_row_matches": rows,
        "table_row_checks": len(TABLE_ROWS),
        "native_header_matches": headers,
        "header_checks": sum(len(row[4]) for row in TABLE_ROWS),
    }


def _load(directory: Path, *, parser: str) -> dict[str, Any]:
    parses = {}
    for document, expected_hash in DOCUMENTS.items():
        path = directory / f"{document}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        identity = data["identity"]
        if identity["document"] != document or identity["source_sha256"] != expected_hash:
            raise ValueError(f"wrong source identity in {path}")
        if identity["parser"] != parser:
            raise ValueError(f"wrong parser identity in {path}")
        first, last = identity["page_range"]
        if [page["page_number"] for page in data["pages"]] != list(range(first - 1, last)):
            raise ValueError(f"invalid page provenance in {path}")
        parses[document] = data
    return parses


def _parse_summary(
    parses: dict[str, Any], directory: Path, records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report = {
        "seconds": round(sum(item["parse_seconds"] for item in parses.values()), 3),
        "peak_memory_bytes": max(item["peak_memory_bytes"] for item in parses.values()),
        "artifact_bytes": sum((directory / f"{doc}.json").stat().st_size for doc in parses),
        "pages": sum(len(item["pages"]) for item in parses.values()),
        "unassigned_blocks": sum(item["unassigned_blocks"] for item in parses.values()),
        "audit": audit_pages(parses),
        "versions": next(iter(parses.values()))["identity"]["versions"],
        "model_sha256": next(iter(parses.values()))["identity"]["model_sha256"],
    }
    if records is not None:
        report["text_recovery"] = evidence_alignment_stats(records, {
            document: {page["page_number"]: page["text"] for page in item["pages"]}
            for document, item in parses.items()
        })
    return report


def _dense(embedder: Any, cases: list, query_vectors: Any, chunks: list[dict[str, Any]]) -> dict:
    import numpy as np

    chunks = sorted(chunks, key=lambda item: item["chunk_id"])
    started = time.perf_counter()
    vectors = np.asarray(
        embedder.embed_documents([item["text"] for item in chunks], show_progress_bar=False),
        dtype=np.float32,
    )
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    embed_seconds = time.perf_counter() - started
    ranked = {}
    recall50 = []
    timings = {}
    for case, vector in zip(cases, query_vectors, strict=True):
        started = time.perf_counter()
        order = np.argsort(-(vectors @ vector), kind="stable")[:50]
        timings[case.case_id] = (time.perf_counter() - started) * 1000
        candidates = [chunks[index] for index in order]
        ranked[case.case_id] = candidates[:10]
        pages = {item["page_number"] for item in candidates if item["doc_name"] == case.doc_name}
        recall50.append(len(pages.intersection(case.gold_pages)) / len(case.gold_pages))
    report = evaluate_retrieval(cases, ranked, timings)
    return {
        "chunk_count": len(chunks),
        "embedding_seconds": round(embed_seconds, 3),
        "Recall@50": round(sum(recall50) / len(recall50), 4),
        "metrics": report["overall"],
        "by_split": report["by_split"],
    }


def main() -> None:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--pypdf", type=Path, required=True)
    command.add_argument("--accurate", type=Path, required=True)
    command.add_argument("--accurate-audit", type=Path)
    command.add_argument("--fast-audit", type=Path)
    command.add_argument("--source", type=Path, default=Path("data/financebench/source"))
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--threads", type=int, default=6)
    command.add_argument("--audit-only", action="store_true")
    args = command.parse_args()
    if not 1 <= args.threads <= 16:
        command.error("threads must be 1–16")

    baseline = _load(args.pypdf, parser="pypdf")
    accurate = _load(args.accurate, parser="accurate")
    for doc in DOCUMENTS:
        baseline_range = baseline[doc]["identity"]["page_range"]
        if baseline_range[0] != 1 or baseline_range != accurate[doc]["identity"]["page_range"]:
            raise ValueError(f"full parser coverage differs for {doc}")
    case_file = args.source / "financebench_open_source.jsonl"
    records = [
        row for row in map(json.loads, case_file.read_text(encoding="utf-8").splitlines())
        if row["financebench_id"] in CASE_IDS
    ]
    cases = [case for case in load_financebench_cases(case_file) if case.case_id in CASE_IDS]
    if {case.case_id for case in cases} != CASE_IDS or any(case.split == "held_out" for case in cases):
        raise ValueError("case set differs from the frozen failure cohort")
    report = {
        "document_count": len(DOCUMENTS), "case_count": len(cases),
        "pypdf": _parse_summary(baseline, args.pypdf, records),
        "docling_accurate": _parse_summary(accurate, args.accurate, records),
    }
    for name, directory in (("accurate", args.accurate_audit), ("fast", args.fast_audit)):
        if directory is not None:
            audit = _load(directory, parser=name)
            if any(len(doc["pages"]) != 1 for doc in audit.values()):
                raise ValueError("the table mode audit expects one source page per document")
            report[f"docling_{name}_audit"] = _parse_summary(audit, directory)
    if not args.audit_only:
        import numpy as np
        import torch

        from src.retrieval.embedder import Embedder

        torch.set_num_threads(args.threads)
        embedder = Embedder(device="cpu", revision=NOMIC_REVISION)
        query_vectors = np.asarray([embedder.embed_query(case.question) for case in cases], dtype=np.float32)
        query_vectors /= np.maximum(np.linalg.norm(query_vectors, axis=1, keepdims=True), 1e-12)
        metadata, _ = normalize_document_metadata([
            json.loads(line) for line in
            (args.source / "financebench_document_information.jsonl").read_text(encoding="utf-8").splitlines()
        ])
        report["dense"] = {}
        for name, parses, structured in (
            ("pypdf", baseline, False),
            ("docling_page", accurate, False),
            ("docling_structured", accurate, True),
        ):
            chunks = []
            for document, parse in parses.items():
                pages = parse["pages"]
                if structured:
                    chunks.extend(chunk_docling_pages(pages, document_metadata=metadata[document]))
                else:
                    page_chunks, _ = chunk_pdf_pages(pages, document_metadata=metadata[document])
                    chunks.extend(page_chunks)
            print(f"scoring {name}, {len(chunks)} chunks", flush=True)
            report["dense"][name] = _dense(embedder, cases, query_vectors, chunks)
        report["embedding_revision"] = NOMIC_REVISION
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(args.output, flush=True)


if __name__ == "__main__":
    main()
