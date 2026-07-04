from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import SplitResult, urlsplit, urlunsplit


class UnsafeUrlError(ValueError):
    pass


Resolver = Callable[[str], Iterable[str]]


def default_resolver(hostname: str) -> list[str]:
    return sorted(
        {
            item[4][0]
            for item in socket.getaddrinfo(
                hostname,
                None,
                type=socket.SOCK_STREAM,
            )
        }
    )


def _is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def normalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeUrlError("Only http and https URLs are allowed")
    if not parsed.hostname:
        raise UnsafeUrlError("URL hostname is required")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("Credentials in URLs are not allowed")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or "/"
    return urlunsplit(
        SplitResult(
            parsed.scheme.lower(),
            f"{host}{port}",
            path,
            parsed.query,
            "",
        )
    )


def validate_url(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    allowed_path_prefixes: tuple[str, ...] = ("/",),
    resolver: Resolver = default_resolver,
    resolve_dns: bool = True,
) -> str:
    normalized = normalize_url(url)
    parsed = urlsplit(normalized)
    hostname = parsed.hostname or ""
    allowed = {item.encode("idna").decode("ascii").lower() for item in allowed_hosts}
    if hostname not in allowed:
        raise UnsafeUrlError(f"Host is outside the source allowlist: {hostname}")
    if not any(parsed.path.startswith(prefix) for prefix in allowed_path_prefixes):
        raise UnsafeUrlError(f"Path is outside the source allowlist: {parsed.path}")
    if resolve_dns:
        addresses = list(resolver(hostname))
        if not addresses:
            raise UnsafeUrlError(f"Hostname did not resolve: {hostname}")
        if not all(_is_public_address(address) for address in addresses):
            raise UnsafeUrlError(f"Hostname resolves to a non-public address: {hostname}")
    return normalized

