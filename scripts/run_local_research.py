"""Serve the evidence-first FilingScope workspace on IPv4 loopback."""

from __future__ import annotations

import argparse
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any

from src.agent.research_progress import ResearchProgress
from src.agent.specialist_graph import SpecialistResearchGraph
from src.local_research import public_result


LOGGER = logging.getLogger(__name__)
ASSET_DIR = Path(__file__).resolve().parents[1] / "src" / "research_ui"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/research.css": ("research.css", "text/css; charset=utf-8"),
    "/research.js": ("research.js", "text/javascript; charset=utf-8"),
}
MAX_REQUEST_BYTES = 8192
MAX_QUESTION_LENGTH = 1000


class LocalResearchServer(ThreadingHTTPServer):
    def __init__(self, port: int, graph: SpecialistResearchGraph):
        super().__init__(("127.0.0.1", port), ResearchHandler)
        self.graph = graph
        self.research_lock = Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(15)
        return connection, address


class ResearchHandler(BaseHTTPRequestHandler):
    server: LocalResearchServer

    def log_request(self, code="-", size="-"):
        # Requests contain research questions. Keep input out of server logs.
        pass

    def _is_local(self) -> bool:
        return (
            self.headers.get("Host") == self.server.url.removeprefix("http://")
            and self.headers.get("Origin", self.server.url) == self.server.url
        )

    def _headers(self, status: HTTPStatus, content_type: str, length: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _error(self, status: HTTPStatus, message: str) -> None:
        body = json.dumps({"message": message}).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._is_local():
            self._error(HTTPStatus.FORBIDDEN, "Open the workspace at its loopback address.")
            return
        if self.path not in ASSETS:
            self._error(HTTPStatus.NOT_FOUND, "Page not found.")
            return
        filename, content_type = ASSETS[self.path]
        body = (ASSET_DIR / filename).read_bytes()
        self._headers(HTTPStatus.OK, content_type, len(body))
        self.wfile.write(body)

    def _request_input(self) -> tuple[str, str] | None:
        if self.headers.get_content_type() != "application/json":
            self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send the question as JSON.")
            return None
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_REQUEST_BYTES:
                raise ValueError
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict) or data.keys() - {"question", "mode"}:
                raise ValueError
            question = data.get("question")
            mode = data.get("mode", "auto")
            if not isinstance(question, str) or not 0 < len(question.strip()) <= MAX_QUESTION_LENGTH:
                raise ValueError
            if mode not in ("auto", "research"):
                raise ValueError
            question.encode("utf-8")
        except (ValueError, RecursionError, TimeoutError):
            self._error(HTTPStatus.BAD_REQUEST, "Enter a question of 1–1,000 characters and a valid search mode.")
            return None
        return question.strip(), mode

    def do_POST(self) -> None:
        if not self._is_local():
            self._error(HTTPStatus.FORBIDDEN, "Open the workspace at its loopback address.")
            return
        if self.path != "/api/research":
            self._error(HTTPStatus.NOT_FOUND, "Page not found.")
            return
        inputs = self._request_input()
        if inputs is None:
            return
        if not self.server.research_lock.acquire(blocking=False):
            self._error(HTTPStatus.CONFLICT, "Another question is running. Try again when it finishes.")
            return
        try:
            self._headers(HTTPStatus.OK, "application/x-ndjson; charset=utf-8")
            question, mode = inputs
            try:
                execution = self.server.graph.run(question, force_research=mode == "research", on_progress=self._progress)
                self._event({"type": "result", "result": public_result(execution)})
            except (ConnectionError, TimeoutError):
                return
            except Exception as error:
                LOGGER.error("Local research failed (%s)", type(error).__name__)
                try:
                    self._event({"type": "error", "message": "Research could not finish. Retry the question."})
                except (ConnectionError, TimeoutError):
                    return
        finally:
            self.server.research_lock.release()

    def _progress(self, stage: ResearchProgress) -> None:
        self._event({"type": "progress", "stage": stage.value})

    def _event(self, record: dict[str, Any]) -> None:
        body = json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.wfile.write(body + b"\n")
        self.wfile.flush()


def main() -> None:
    from configs.hard_negatives import P1_EMBEDDING_REVISION, P1_INDEX_ID
    from configs.multi_agent_ablation import COMPANY_TICKERS, SEC_CUTOFF, SEC_ISSUERS
    from scripts.run_hard_negative_retrieval import DEFAULT_RUN, _load_corpus, _load_vectors

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--p1-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--sec-dir", type=Path, default=Path("data/financebench/ablation_runs/m13-sec"))
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.threads <= 16 or not 0 <= args.port <= 65535:
        parser.error("use 1–16 threads and a valid loopback port")

    import torch

    from src.agent.complexity_router import ComplexityRouter
    from src.evaluation.company_facts_replay import CompanyFactsReplay
    from src.research.corpus_map import CorpusMap
    from src.retrieval.embedder import Embedder
    from src.retrieval.frozen_dense import FrozenDenseRetriever

    torch.set_num_threads(args.threads)
    print("Loading the frozen FinanceBench index and SEC snapshots…", flush=True)
    chunks = _load_corpus(args.p1_run)
    vectors = _load_vectors(args.p1_run, chunks)
    sec = CompanyFactsReplay(args.sec_dir, SEC_ISSUERS, latest_filed=SEC_CUTOFF)
    graph = SpecialistResearchGraph(
        router=ComplexityRouter(CorpusMap.from_chunks(chunks, index_generation_id=P1_INDEX_ID)),
        retriever=FrozenDenseRetriever(chunks, vectors, Embedder(device="cpu", revision=P1_EMBEDDING_REVISION)),
        sec_client=sec,
        ticker_by_company=COMPANY_TICKERS,
    )
    with LocalResearchServer(args.port, graph) as server:
        print(f"FilingScope is ready at {server.url}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
