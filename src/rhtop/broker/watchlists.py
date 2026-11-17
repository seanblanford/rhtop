"""Display-only watchlist reads using the discovered MCP schemas."""

from dataclasses import dataclass

from ..errors import SchemaError
from .catalog import catalog_rows


@dataclass(frozen=True)
class Watchlist:
    identifier: str
    name: str
    owner: str = "custom"
    options: bool = False


class WatchlistReader:
    def __init__(self, broker):
        self.broker = broker

    async def lists(self) -> tuple[Watchlist, ...]:
        rows, _ = await catalog_rows(
            self.broker, "get_watchlists", {}, ("watchlists",), complete=True
        )
        result = []
        for row in rows:
            if not isinstance(row.get("id"), str) or not row["id"]:
                raise SchemaError("Watchlist identifier is missing")
            result.append(
                Watchlist(
                    row["id"],
                    str(row.get("display_name", "Untitled")),
                    str(row.get("owner_type", "custom")),
                    "option_strategy" in (row.get("allowed_object_types") or []),
                )
            )
        return tuple(result)

    async def items(self, watchlist: Watchlist) -> tuple[str, ...]:
        tool = "get_option_watchlist" if watchlist.options else "get_watchlist_items"
        values = {} if watchlist.options else {"list_id": watchlist.identifier}
        if values:
            self.broker.arguments(tool, values, required_keys=("list_id",))
        rows, _ = await catalog_rows(self.broker, tool, values, ("items",), complete=True)
        if watchlist.options:
            return tuple(
                f"{row.get('name') or row.get('chain_symbol') or 'Unknown'} · "
                f"{row.get('position_type', '—')} · {row.get('expiration_date', '—')}"
                for row in rows
            )
        return tuple(
            f"{row.get('symbol') or 'Unknown'} · {row.get('object_type', 'unknown')}"
            for row in rows
        )
