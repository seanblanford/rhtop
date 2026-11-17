"""Read-only asset discovery using the server's published search/catalog tools."""

import re

from ..assets import Asset, AssetResults
from ..errors import SchemaError
from .catalog import catalog_rows
from .parsing import records


class AssetReader:
    def __init__(self, broker):
        self.broker = broker

    async def browse(self, kind: str, query: str = "", *, underlying: bool = False) -> AssetResults:
        if kind == "crypto":
            rows, _ = await catalog_rows(
                self.broker,
                "get_currency_pairs",
                {"limit": 700},
                ("currency_pairs", "pairs"),
                complete=True,
            )
            assets = []
            for row in rows:
                currency = row.get("asset_currency") or {}
                assets.append(
                    Asset(
                        "crypto",
                        str(row.get("symbol") or currency.get("code") or "Unknown"),
                        str(currency.get("name") or row.get("name") or ""),
                        str(row.get("id", "")),
                        str(row.get("tradability", "")),
                        bool(row.get("halted") or row.get("halted_regions")),
                        " ".join(row.get("halted_regions") or []),
                    )
                )
            assets = sorted(assets, key=lambda row: row.symbol)
            if query:
                assets = [row for row in assets if query.casefold() in row.title.casefold()]
            return AssetResults(
                tuple(assets), "All supported pairs · regional halts may be one-sided"
            )
        query = query.strip()
        if not query:
            return AssetResults((), "Search a company or ticker; Enter a result to save it")
        if kind not in ("equity", "option"):
            raise SchemaError("Unsupported asset category")
        contract_filter = any(
            re.fullmatch(r"\d{4}-\d{2}-\d{2}|call|put|\d+(\.\d+)?", part, re.IGNORECASE)
            for part in query.split()[1:]
        )
        if kind == "option" and (underlying or contract_filter):
            return await self.contracts(query)
        arguments = self.broker.arguments(
            "search",
            {"query": query, "asset_type": "instrument", "limit": 20},
            required_keys=("query",),
        )
        rows = records(await self.broker.call("search", arguments), "results")
        return AssetResults(
            tuple(
                Asset(
                    kind,
                    str(row.get("symbol", "Unknown")),
                    str(row.get("simple_name") or row.get("name") or ""),
                    str(row.get("instrument_id", "")),
                    underlying=kind == "option",
                )
                for row in rows
            ),
            "Choose an underlying to browse its contracts"
            if kind == "option"
            else "Enter a result to inspect and save it",
        )

    async def contracts(self, query: str) -> AssetResults:
        # Optional expiry, right, strike narrow large chains without inventing any values.
        parts = query.split()
        symbol = parts[0].upper()
        values = {"chain_symbol": symbol}
        for part in parts[1:]:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", part):
                values["expiration_dates"] = [part]
            elif part.lower() in ("call", "put"):
                values["type"] = part.lower()
            elif re.fullmatch(r"\d+(\.\d+)?", part):
                values["strike_price"] = part
            else:
                raise SchemaError(
                    "Use SYMBOL [YYYY-MM-DD] [call|put] [strike] for option contracts"
                )
        tool = "get_option_instruments"
        props = self.broker.schemas.get(tool, {}).get("properties", {})
        if "chain_symbol" not in props:
            raise SchemaError("Option instrument tool cannot preserve the underlying symbol")
        arguments = self.broker.arguments(tool, values, required_keys=tuple(values))
        rows, partial = await catalog_rows(
            self.broker, tool, arguments, ("instruments",), limit=500
        )
        assets = []
        for row in rows:
            if row.get("chain_symbol", row.get("symbol")) != symbol:
                continue
            assets.append(
                Asset(
                    "option",
                    symbol,
                    identifier=str(row.get("id", "")),
                    state=str(row.get("state", "")) + " / " + str(row.get("tradability", "")),
                    expiration=str(row.get("expiration_date", "")),
                    strike=str(row.get("strike_price", "")),
                    option_type=str(row.get("type", "")),
                )
            )
        return AssetResults(
            tuple(assets),
            "First 500 contracts · narrow with expiry/right/strike"
            if partial
            else "Enter a contract to inspect and save to recents",
        )
