"""Compare concurrency limits with the same simulated filing search workload."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time

from src.agent.complexity_router import ComplexityRouter
from src.agent.specialist_graph import SpecialistResearchGraph, SpecialistUsage


QUESTION = "Compare Apple and Microsoft revenue for FY2022, FY2023, and FY2024."


class DelayedRetriever:
    supports_concurrent_retrieval = True

    def __init__(self, delay_seconds: float):
        self.delay_seconds = delay_seconds

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        time.sleep(self.delay_seconds)
        return []


def summarize(samples: list[SpecialistUsage]) -> dict:
    latencies = sorted(sample.wall_time_ms for sample in samples)
    return {
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(latencies[math.ceil(0.95 * len(latencies)) - 1], 2),
        "peak_parallel_tasks": max(sample.peak_parallel_tasks for sample in samples),
        "retrieval_calls_per_run": sorted({sample.retrieval_calls for sample in samples}),
        "tool_calls_per_run": sorted({sample.tool_calls for sample in samples}),
        "llm_calls_per_run": sorted({sample.llm_calls for sample in samples}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--delay-ms", type=float, default=40.0)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 100 or not 0 < args.delay_ms <= 1000:
        parser.error("iterations must be 1–100 and delay-ms must be greater than 0 and at most 1000")

    router = ComplexityRouter()
    route = router.route(QUESTION)
    serial = route.model_copy(update={"budget": route.budget.model_copy(update={"max_concurrency": 1})})
    routes = {"serial": serial, "parallel": route}
    graph = SpecialistResearchGraph(router=router, retriever=DelayedRetriever(args.delay_ms / 1000))
    samples: dict[str, list[SpecialistUsage]] = {name: [] for name in routes}
    for variant in routes.values():
        graph.run(QUESTION, route=variant)
    for _ in range(args.iterations):
        for name, variant in routes.items():
            samples[name].append(graph.run(QUESTION, route=variant).usage)
    print(json.dumps({
        "fixture": "six scoped filing queries with simulated blocking I/O and empty results",
        "iterations_per_mode": args.iterations,
        "simulated_delay_ms": args.delay_ms,
        "modes": {name: summarize(values) for name, values in samples.items()},
    }, indent=2))


if __name__ == "__main__":
    main()
