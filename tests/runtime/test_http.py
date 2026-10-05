"""Unit tests for the restricted HTTP client: URL joining, whitelist and assertions."""

from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from project_doctor.integrations.http.requests import (
    HttpResponse,
    RestrictedHttpClient,
    address_in_network,
    check_assertions,
    join_url,
)
from project_doctor.models.scenario import Assertions, BusinessAssertion, RequestStep

# --- URL joining ------------------------------------------------------------


def test_join_url_tolerates_slashes() -> None:
    assert join_url("http://127.0.0.1:18080", "/orders") == "http://127.0.0.1:18080/orders"
    assert join_url("http://127.0.0.1:18080/", "orders") == "http://127.0.0.1:18080/orders"


# --- network whitelist ------------------------------------------------------


def test_address_in_network_membership() -> None:
    assert address_in_network("127.0.0.1", "127.0.0.0/8")
    assert not address_in_network("10.0.0.1", "127.0.0.0/8")


def test_address_in_network_rejects_invalid_input() -> None:
    assert not address_in_network("not-an-ip", "127.0.0.0/8")
    assert not address_in_network("127.0.0.1", "not-a-cidr")


# --- assertion evaluation ---------------------------------------------------


def test_check_assertions_accepts_matching_status_and_existence() -> None:
    assertions = Assertions(
        status_code=200, business=[BusinessAssertion(json_pointer="/items", operator="exists")]
    )
    response = HttpResponse(status_code=200, body={"items": [1]}, latency_ms=10.0, headers={})
    assert check_assertions(assertions, response) == (True, [])


def test_check_assertions_flags_status_mismatch() -> None:
    assertions = Assertions(
        status_code=200, business=[BusinessAssertion(json_pointer="/items", operator="exists")]
    )
    response = HttpResponse(status_code=404, body={"items": [1]}, latency_ms=10.0, headers={})
    valid, reasons = check_assertions(assertions, response)
    assert valid is False and any("status" in reason for reason in reasons)


def test_check_assertions_flags_missing_business_field() -> None:
    assertions = Assertions(
        status_code=200, business=[BusinessAssertion(json_pointer="/items", operator="exists")]
    )
    response = HttpResponse(status_code=200, body={}, latency_ms=10.0, headers={})
    assert check_assertions(assertions, response)[0] is False


def test_check_assertions_equals_operator() -> None:
    assertions = Assertions(
        status_code=200,
        business=[BusinessAssertion(json_pointer="/count", operator="equals", expected=3)],
    )
    assert check_assertions(assertions, HttpResponse(200, {"count": 3}, 1.0, {}))[0] is True
    assert check_assertions(assertions, HttpResponse(200, {"count": 4}, 1.0, {}))[0] is False


# --- query parameter flattening ---------------------------------------------


def test_query_params_keep_scalars_and_flatten_nested() -> None:
    assert RestrictedHttpClient._query_params(
        {"a": 1, "b": "x", "c": None, "d": [1, 2], "e": True}
    ) == {"a": 1, "b": "x", "c": None, "d": "[1,2]", "e": True}


def test_isolated_request_bypasses_host_proxy_and_has_unique_id(monkeypatch) -> None:
    ids = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ids.append(self.headers.get("X-Project-Doctor-Request-Id"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    client = RestrictedHttpClient(f"http://127.0.0.1:{server.server_port}", "127.0.0.0/8", 3)
    step = RequestStep(
        method="GET",
        relative_path="/",
        assertions=Assertions(
            status_code=200,
            business=[BusinessAssertion(json_pointer="/ok", operator="equals", expected=True)],
        ),
    )
    try:
        first = asyncio.run(client.request(step))
        second = asyncio.run(client.request(step))
        assert first.body == second.body == {"ok": True}
        assert ids == [first.request_id, second.request_id]
        assert len(set(ids)) == 2
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
