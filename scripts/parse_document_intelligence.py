"""Parse the frozen M10 PDF subset into restartable local artifacts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
import time
from pathlib import Path

from pypdf import PdfReader

from configs.document_intelligence import DOCUMENTS, READING_ORDER


AUDIT_PAGES = {document: page + 1 for document, page in READING_ORDER}


def _peak_memory_bytes() -> int:
    if sys.platform == "win32":
        import psutil

        return psutil.Process().memory_info().peak_wset
    import resource

    multiplier = 1 if sys.platform == "darwin" else 1024
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * multiplier


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--parser", choices=("pypdf", "accurate", "fast"), required=True)
    command.add_argument("--pdf-dir", type=Path, default=Path("data/financebench/pdfs"))
    command.add_argument("--output-dir", type=Path, required=True)
    command.add_argument("--artifacts", type=Path)
    command.add_argument("--threads", type=int, default=4)
    command.add_argument("--audit-only", action="store_true")
    command.add_argument("--document", choices=tuple(DOCUMENTS), action="append")
    args = command.parse_args()
    if not 1 <= args.threads <= 16:
        command.error("threads must be 1–16")
    converter = None
    model_hashes = {}
    if args.parser == "pypdf":
        from src.ingestion.pdf_ingestion import extract_pdf_pages

        versions = {name: importlib.metadata.version(name) for name in ("pypdf", "fonttools")}
    else:
        if args.artifacts is None or not args.artifacts.is_dir():
            command.error("Docling needs the local layout and TableFormer artifacts directory")
        from src.ingestion.docling_pdf import DoclingParser

        versions = {
            name: importlib.metadata.version(name)
            for name in ("docling", "docling-core", "docling-ibm-models", "docling-parse", "torch")
        }
        model_hashes = {
            path.relative_to(args.artifacts).as_posix(): _sha256(path)
            for path in sorted(args.artifacts.rglob("*"))
            if path.is_file() and path.suffix in {".safetensors", ".pt", ".bin"}
        }
        converter = DoclingParser(
            artifacts_path=args.artifacts, table_mode=args.parser, threads=args.threads,
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for document, expected_hash in DOCUMENTS.items():
        if args.document and document not in args.document:
            continue
        path = args.pdf_dir / f"{document}.pdf"
        if _sha256(path) != expected_hash:
            raise ValueError(f"source PDF hash differs for {document}")
        page_count = len(PdfReader(path, strict=False).pages)
        audit_page = AUDIT_PAGES[document]
        bounds = (audit_page, audit_page) if args.audit_only else (1, page_count)
        identity = {
            "document": document, "source_sha256": expected_hash, "parser": args.parser,
            "versions": versions, "model_sha256": model_hashes,
            "page_range": list(bounds), "threads": args.threads,
        }
        output = args.output_dir / f"{document}.json"
        if output.is_file():
            existing = json.loads(output.read_text(encoding="utf-8"))
            if existing.get("identity") != identity:
                raise ValueError(f"existing parse does not match {output.name}")
            print(f"reused {document}", flush=True)
            continue
        print(f"parsing {document} pages {bounds[0]}–{bounds[1]}", flush=True)
        started = time.perf_counter()
        if converter is None:
            pages = extract_pdf_pages(path)[bounds[0] - 1:bounds[1]]
            data = {"pages": pages, "unassigned_blocks": 0}
        else:
            data = converter.extract(path, page_range=bounds)
        data.update(
            identity=identity, parse_seconds=round(time.perf_counter() - started, 3),
            peak_memory_bytes=_peak_memory_bytes(),
        )
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(output)
        print(f"parsed {document} in {data['parse_seconds']}s", flush=True)


if __name__ == "__main__":
    main()
