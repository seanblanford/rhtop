"""Cursor-aware MCP catalog reads; never silently truncate crypto."""

from ..errors import SchemaError
from .parsing import records, unwrap


async def catalog_rows(broker, tool, values, keys, limit=10000, *, complete=False):
    rows, seen, cursor = [], set(), None
    for _ in range(100):
        arguments = broker.arguments(tool, {**values, "cursor": cursor})
        if cursor and arguments.get("cursor") != cursor:
            raise SchemaError(f"{tool} cannot preserve its pagination cursor")
        response = await broker.call(tool, arguments)
        page = records(response, *keys)
        remaining = max(0, limit - len(rows))
        overflow = len(page) > remaining
        rows.extend(page[:remaining])
        value = unwrap(response)
        cursor = value.get("next", value.get("next_cursor")) if isinstance(value, dict) else None
        if not cursor:
            if isinstance(value, dict) and (value.get("has_more") or value.get("next_page_token")):
                raise SchemaError(f"{tool} returned unsupported pagination")
            if complete and overflow:
                raise SchemaError(f"{tool} catalog exceeds the supported bound")
            return rows, overflow
        if not isinstance(cursor, str) or cursor in seen:
            raise SchemaError(f"{tool} returned an invalid pagination cursor")
        seen.add(cursor)
        if len(rows) >= limit:
            if complete:
                raise SchemaError(f"{tool} catalog exceeds the supported bound")
            return rows, True
    raise SchemaError(f"{tool} exceeded the catalog page limit")
