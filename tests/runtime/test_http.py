"""Unit tests for the restricted HTTP client: URL joining, whitelist and assertions."""

from __future__ import annotations

from project_doctor.integrations.http.requests import (
    HttpResponse,
    RestrictedHttpClient,
    address_in_network,
    check_assertions,
    join_url,
)
from project_doctor.models.scenario import Assertions, BusinessAssertion

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
