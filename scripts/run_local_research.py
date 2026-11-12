"""Serve the evidence-first FilingScope workspace on IPv4 loopback."""

from __future__ import annotations

import argparse
import json
import logging
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any

from src.agent.research_progress import ResearchProgress
from src.agent.specialist_graph import SpecialistResearchGraph
from src.generation.grounded_writer import ProviderLimits
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
                provider = getattr(self.server.graph, "provider_writer", None)
                prior_calls = provider.usage.attempted_calls if provider else 0
                execution = self.server.graph.run(question, force_research=mode == "research", on_progress=self._progress)
                if provider and provider.usage.attempted_calls != prior_calls:
                    usage = provider.usage
                    LOGGER.info("Provider %s attempts=%d responses=%d observed_input=%d observed_output=%d "
                                "reported_cost_usd=%s reserved_cost_usd=%s missing_usage=%d budget_breached=%s",
                                getattr(provider.generator, "model_id", "injected"), usage.attempted_calls, usage.responses,
                                usage.observed_input_tokens, usage.observed_output_tokens, usage.reported_cost_usd,
                                usage.cost_upper_bound_usd, usage.missing_usage_responses, usage.budget_breached)
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
    from configs.financebench import P1_EMBEDDING_REVISION, P1_INDEX_ID, P1_PAGE_CACHE, P1_RUN
    from configs.sec_snapshots import COMPANY_TICKERS, SEC_CUTOFF, SEC_ISSUERS
    from src.retrieval.frozen_artifacts import load_frozen_corpus, load_frozen_vectors

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--p1-run", type=Path, default=P1_RUN)
    parser.add_argument("--statement-pages", type=Path, help="Pinned pypdf page cache for table normalization")
    parser.add_argument("--retrieval-policy", choices=("statement", "dense"), default="statement",
                        help="Rank scoped filing evidence by requested statement slots or use Dense alone")
    parser.add_argument("--sec-dir", type=Path, default=Path("data/financebench/ablation_runs/m13-sec"))
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--provider-run", action="store_true", help="Enable the budgeted Groq narrative writer")
    parser.add_argument("--max-provider-calls", type=int)
    parser.add_argument("--max-provider-input-tokens", type=int)
    parser.add_argument("--max-provider-output-tokens", type=int)
    parser.add_argument("--max-provider-cost-usd", type=Decimal)
    parser.add_argument("--max-correction-passes", type=int, choices=(0, 1), default=1)
    args = parser.parse_args()
    if not 1 <= args.threads <= 16 or not 0 <= args.port <= 65535:
        parser.error("use 1–16 threads and a valid loopback port")
    budget_options = {"max_calls": args.max_provider_calls, "max_input_tokens": args.max_provider_input_tokens,
                      "max_output_tokens": args.max_provider_output_tokens, "max_cost_usd": args.max_provider_cost_usd}
    provider_limits = None
    generator = None
    if args.provider_run:
        from pydantic import ValidationError

        try:
            provider_limits = ProviderLimits(**budget_options)
        except ValidationError:
            parser.error("--provider-run requires positive call, input, output, and finite cost limits")
        from configs.end_to_end import GENERATOR_MAX_OUTPUT_TOKENS
        from configs.settings import settings
        from src.generation.answer_generator import GroqAnswerGenerator

        key = settings.groq_api_key.get_secret_value()
        if not key:
            parser.error("--provider-run requires GROQ_API_KEY in the local environment")
        generator = GroqAnswerGenerator(
            api_key=key, max_output_tokens=min(GENERATOR_MAX_OUTPUT_TOKENS, provider_limits.max_output_tokens),
            timeout_seconds=10.0,
        )
        LOGGER.setLevel(logging.INFO)
        LOGGER.addHandler(logging.StreamHandler())
        LOGGER.info("Enabled provider groq model=%s", generator.model_id)
    elif any(value is not None for value in budget_options.values()):
        parser.error("provider limits require --provider-run")

    import torch

    from src.agent.complexity_router import ComplexityRouter
    from src.evaluation.company_facts_replay import CompanyFactsReplay
    from src.research.corpus_map import CorpusMap
    from src.retrieval.embedder import Embedder
    from src.retrieval.financial_statement_ranker import FinancialStatementRanker
    from src.retrieval.frozen_dense import FrozenDenseRetriever
    from src.retrieval.pdf_page_cache import FrozenPdfPages

    torch.set_num_threads(args.threads)
    print("Loading the frozen FinanceBench index and SEC snapshots…", flush=True)
    chunks = load_frozen_corpus(args.p1_run)
    vectors = load_frozen_vectors(args.p1_run, chunks)
    sec = CompanyFactsReplay(args.sec_dir, SEC_ISSUERS, latest_filed=SEC_CUTOFF)
    page_path = args.statement_pages or (P1_PAGE_CACHE if P1_PAGE_CACHE.is_file() else None)
    pages = FrozenPdfPages.from_run(page_path, args.p1_run) if page_path is not None else None
    router = ComplexityRouter(CorpusMap.from_chunks(chunks, index_generation_id=P1_INDEX_ID))
    statement_ranker = FinancialStatementRanker(pages, router.extractor) if pages and args.retrieval_policy == "statement" else None
    graph = SpecialistResearchGraph(
        router=router,
        retriever=FrozenDenseRetriever(
            chunks, vectors, Embedder(device="cpu", revision=P1_EMBEDDING_REVISION),
            pdf_pages=pages, statement_ranker=statement_ranker,
        ),
        sec_client=sec,
        generator=generator,
        provider_limits=provider_limits,
        max_correction_passes=args.max_correction_passes,
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
