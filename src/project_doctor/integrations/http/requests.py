"""Restricted HTTP client: join, whitelist and run one scenario request step."""

from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from project_doctor.models.scenario import Assertions, RequestStep

_MISSING = object()


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: Any
    latency_ms: float
    headers: dict[str, str]


def join_url(base_url: str, relative_path: str) -> str:
    """Join a service base URL with a request-relative path, tolerating slashes."""
    return urljoin(base_url.rstrip("/") + "/", relative_path.lstrip("/"))


def address_in_network(address: str, network_cidr: str) -> bool:
    """Whether a single IP address belongs to a strict CIDR network."""
    try:
        return ipaddress.ip_address(address) in ipaddress.ip_network(network_cidr, strict=True)
    except ValueError:
        return False


def resolve_host(host: str) -> list[str]:
    """All IP addresses the host resolves to, sorted for determinism."""
    addresses: set[str] = set()
    for info in socket.getaddrinfo(host, None):
        sockaddr = info[4]
        address = sockaddr if isinstance(sockaddr, str) else sockaddr[0]
        if isinstance(address, str):
            addresses.add(address)
    return sorted(addresses)


def check_assertions(assertions: Assertions, response: HttpResponse) -> tuple[bool, list[str]]:
    """Evaluate status and business assertions; returns ``(valid, reasons)``."""
    reasons: list[str] = []
    if response.status_code != assertions.status_code:
        reasons.append(f"status {response.status_code} != {assertions.status_code}")
    for assertion in assertions.business:
        value = _lookup(response.body, assertion.json_pointer)
        if assertion.operator == "exists":
            if value is _MISSING:
                reasons.append(f"{assertion.json_pointer} is missing")
        elif assertion.operator == "equals" and value != assertion.expected:
            reasons.append(f"{assertion.json_pointer} does not equal the expected value")
    return not reasons, reasons


def _lookup(body: Any, pointer: str) -> Any:
    """Resolve a JSON pointer like ``/count`` against a decoded body."""
    if not pointer:
        return body
    current = body
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current.get(token, _MISSING)
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return _MISSING
    return current


class RestrictedHttpClient:
    """Sends a request only after the target host resolves inside the allowed network."""

    def __init__(self, base_url: str, allowed_network: str, timeout: float) -> None:
        self._base_url = base_url
        self._allowed_network = allowed_network
        self._timeout = timeout

    def endpoint(self, relative_path: str) -> str:
        url = join_url(self._base_url, relative_path)
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("request target must be an HTTP(S) URL with a host")
        addresses = resolve_host(parsed.hostname)
        if not any(address_in_network(address, self._allowed_network) for address in addresses):
            raise ValueError("request target host is outside the allowed network")
        return url

    async def request(self, step: RequestStep) -> HttpResponse:
        url = self.endpoint(step.relative_path)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.request(
                step.method, url, params=self._query_params(step.params) or None
            )
            try:
                body: Any = response.json()
            except ValueError:
                body = response.text
            return HttpResponse(
                status_code=response.status_code,
                body=body,
                latency_ms=response.elapsed.total_seconds() * 1000,
                headers=dict(response.headers),
            )

    @staticmethod
    def _query_params(
        params: dict[str, Any],
    ) -> dict[str, str | int | float | bool | None]:
        """Flatten nested JSON params into scalar query values httpx can send."""
        scalars = (str, int, float, bool)
        return {
            key: value
            if value is None or isinstance(value, scalars)
            else json.dumps(value, separators=(",", ":"), ensure_ascii=False)
            for key, value in params.items()
        }
