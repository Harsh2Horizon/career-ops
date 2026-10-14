from __future__ import annotations

import ipaddress
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from career_ops.common.io import CareerOpsError


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise CareerOpsError("unsafe_url", "Use an absolute HTTP(S) URL without credentials")
    if any(ord(c) < 32 for c in value) or "\\" in value:
        raise CareerOpsError("unsafe_url", "Invalid URL characters")
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
        and k.lower() not in {"ref", "source", "trackingid", "trk", "fbclid", "gclid"}
    ]
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    if port and not (
        parsed.scheme == "https" and port == 443 or parsed.scheme == "http" and port == 80
    ):
        host += f":{port}"
    return urlunsplit(
        (parsed.scheme.lower(), host, parsed.path.rstrip("/") or "/", urlencode(sorted(query)), "")
    )


def validate_url(
    value: str, *, allowed_hosts: list[str] | None = None, mock: bool = False, resolve: bool = True
) -> str:
    canonical = canonical_url(value)
    parsed = urlsplit(canonical)
    host = parsed.hostname
    if mock:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise CareerOpsError("mock_only", "Mock mode accepts only loopback URLs")
        return canonical
    if parsed.scheme != "https":
        raise CareerOpsError("https_required", "Real job/application destinations must use HTTPS")
    if allowed_hosts is not None and host not in allowed_hosts:
        raise CareerOpsError(
            "host_not_authorized", f"Authorize this exact application host in config: {host}"
        )
    if resolve:
        try:
            addresses = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise CareerOpsError("dns_failed", "Destination DNS lookup failed") from exc
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise CareerOpsError(
                "private_destination", "Private, loopback, and reserved destinations are blocked"
            )
    return canonical


def redacted(value: str, sensitive: bool = False) -> str:
    return "[redacted]" if sensitive else value
