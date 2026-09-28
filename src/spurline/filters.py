from __future__ import annotations

from typing import Any

from .events import StoredEvent


class FilterValidationError(ValueError):
    pass


def validate_filter_bounds(filters: list[dict[str, Any]]) -> None:
    if len(filters) > 16:
        raise FilterValidationError("at most 16 filters are allowed")
    for relay_filter in filters:
        values_count = 0
        for key, value in relay_filter.items():
            values = value if isinstance(value, list) else [value]
            values_count += len(values)
            if values_count > 2000:
                raise FilterValidationError("at most 2000 values per filter are allowed")
            for item in values:
                if isinstance(item, int) and not -(2**63) <= item < 2**63:
                    raise FilterValidationError("filter integers must fit signed 64-bit range")
                if isinstance(item, str) and len(item) > 4096:
                    raise FilterValidationError("filter strings must not exceed 4096 characters")
            if key in {"ids", "authors"} and sum(len(p) != 64 for p in value) > 128:
                raise FilterValidationError("at most 128 prefixes per field are allowed")


def matches_filter(event: StoredEvent, relay_filter: dict[str, Any]) -> bool:
    if "ids" in relay_filter and not _matches_prefixes(event.id, relay_filter["ids"]):
        return False
    if "authors" in relay_filter and not _matches_prefixes(event.pubkey, relay_filter["authors"]):
        return False
    if "kinds" in relay_filter and event.kind not in relay_filter["kinds"]:
        return False
    if "since" in relay_filter and event.created_at < relay_filter["since"]:
        return False
    if "until" in relay_filter and event.created_at > relay_filter["until"]:
        return False

    for key, values in relay_filter.items():
        if not key.startswith("#"):
            continue
        tag_name = key[1:]
        if not _matches_tag(event, tag_name, values):
            return False

    return True


def matches_any_filter(event: StoredEvent, filters: list[dict[str, Any]]) -> bool:
    return any(matches_filter(event, relay_filter) for relay_filter in filters)


def normalize_filters(filters: list[Any]) -> list[dict[str, Any]]:
    if len(filters) > 16:
        raise FilterValidationError("at most 16 filters are allowed")
    normalized = []
    for relay_filter in filters:
        if not isinstance(relay_filter, dict):
            continue
        clean: dict[str, Any] = {}
        for key, value in relay_filter.items():
            if key in {"ids", "authors"} and _is_string_list(value):
                clean[key] = value
            elif key == "kinds" and _is_int_list(value):
                clean[key] = value
            elif key in {"since", "until", "limit"} and isinstance(value, int):
                clean[key] = value
            elif key.startswith("#") and len(key) == 2 and _is_string_list(value):
                clean[key] = value
        normalized.append(clean)
    validate_filter_bounds(normalized)
    return normalized


def filter_limit(filters: list[dict[str, Any]], default: int = 500, ceiling: int = 5000) -> int:
    requested = [relay_filter["limit"] for relay_filter in filters if "limit" in relay_filter]
    if not requested:
        return default
    return max(1, min(max(requested), ceiling))


def _matches_prefixes(value: str, prefixes: list[str]) -> bool:
    return any(value.startswith(prefix) for prefix in prefixes)


def _matches_tag(event: StoredEvent, tag_name: str, values: list[str]) -> bool:
    return any(
        len(tag) >= 2 and tag[0] == tag_name and tag[1] in values
        for tag in event.tags
    )


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_int_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, int) for item in value)
