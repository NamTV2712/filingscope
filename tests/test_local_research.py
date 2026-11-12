from __future__ import annotations

import json
from http.client import HTTPConnection
from threading import Thread

from scripts.run_local_research import LocalResearchServer
from src.agent.specialist_graph import SpecialistResearchGraph
from src.local_research import _public_url, public_result


def test_source_links_accept_only_credential_free_http() -> None:
    assert _public_url("https://www.sec.gov/Archives/") == "https://www.sec.gov/Archives/"
    for value in ("file:///C:/fixture.pdf", "javascript:alert(1)", "//example.com",
                  "https://[", "https://user:pass@example.com", "https://example.com/\n"):
        assert _public_url(value) is None


def test_rejected_answer_does_not_publish_the_draft() -> None:
    result = SpecialistResearchGraph().run("What was Apple revenue in FY2024?")
    rejected = result.model_copy(update={"status": "REJECTED", "answer": "DO NOT RELEASE"})
    assert "DO NOT RELEASE" not in json.dumps(public_result(rejected))


def test_loopback_stream_and_request_validation() -> None:
    with LocalResearchServer(0, SpecialistResearchGraph()) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for body, origin, expected in [
                ('{"question": "What was Apple revenue in FY2024?"}', "https://unrelated.example", 403),
                ('{"question": "  "}', server.url, 400),
                ('{"question": "What was Apple revenue in FY2024?", "oracle": "G"}', server.url, 400),
                ('{"question": "What was Apple revenue in FY2024?", "mode": "oracle"}', server.url, 400),
                ('{"question": "What stock should I buy?", "mode": "research"}', server.url, 200),
            ]:
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                try:
                    connection.request("POST", "/api/research", body, {
                        "Content-Type": "application/json",
                        "Origin": origin,
                    })
                    response = connection.getresponse()
                    assert response.status == expected
                    if expected != 200:
                        assert "message" in json.loads(response.read())
                        continue
                    assert response.getheader("Content-Type").startswith("application/x-ndjson")
                    events = [json.loads(line) for line in response]
                    assert events[0] == {"type": "progress", "stage": "understanding_question"}
                    assert events[-2] == {"type": "progress", "stage": "finalizing_answer"}
                    assert events[-1]["result"]["status"] == "UNSUPPORTED"
                    assert events[-1]["result"]["attempts"] == []
                finally:
                    connection.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
