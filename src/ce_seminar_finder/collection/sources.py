from __future__ import annotations

from urllib.parse import urlsplit

from ce_seminar_finder.sheets.schema import SOURCES_HEADERS, SOURCE_ROWS

from .models import SourceConfig


DEFAULT_USER_AGENT = (
    "CE-Seminar-Finder-Research/0.2 "
    "(seminar information indexing; one scheduled run per day)"
)


def _value(row: tuple[object, ...], name: str) -> object:
    return row[SOURCES_HEADERS.index(name)]


def source_configs() -> tuple[SourceConfig, ...]:
    configs: list[SourceConfig] = []
    for row in SOURCE_ROWS:
        configs.append(
            SourceConfig(
                source_id=str(_value(row, "source_id")),
                organization_name=str(_value(row, "organization_name")),
                prefecture=str(_value(row, "prefecture")),
                base_url=str(_value(row, "base_url")),
                discovery_urls=tuple(
                    item
                    for item in str(_value(row, "discovery_urls")).splitlines()
                    if item
                ),
                allowed_path_prefixes=tuple(
                    item
                    for item in str(
                        _value(row, "allowed_path_prefixes")
                    ).splitlines()
                    if item
                )
                or ("/",),
                adapter_type=str(_value(row, "adapter_type")),
                text_encoding=str(_value(row, "text_encoding")),
                enabled=bool(_value(row, "enabled")),
                auto_publish_policy=str(_value(row, "auto_publish_policy")),
                request_interval_seconds=float(
                    _value(row, "request_interval_seconds")
                ),
                max_requests_per_run=int(_value(row, "max_requests_per_run")),
                user_agent=(
                    str(_value(row, "user_agent")).strip() or DEFAULT_USER_AGENT
                ),
                robots_url=str(_value(row, "robots_url")),
                notes=str(_value(row, "notes")),
            )
        )
    return tuple(configs)


def source_config(source_id: str) -> SourceConfig:
    for config in source_configs():
        if config.source_id == source_id:
            return config
    raise KeyError(source_id)


def allowed_hosts(config: SourceConfig) -> frozenset[str]:
    hosts = {
        urlsplit(config.base_url).hostname or "",
        *(urlsplit(url).hostname or "" for url in config.discovery_urls),
    }
    expanded = set(hosts)
    for host in tuple(hosts):
        if host.startswith("www."):
            expanded.add(host[4:])
        elif host:
            expanded.add(f"www.{host}")
    return frozenset(host for host in expanded if host)

