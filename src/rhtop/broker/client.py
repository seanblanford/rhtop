"""Authenticated MCP client: live schemas, bounded read retries, no mutation retries."""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from jsonschema import FormatChecker, validators
from mcp import Client
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata
from mcp.shared.exceptions import MCPError

from ..auth import OAuthCallback, TokenVault
from ..config import ConnectionConfig
from ..errors import BrokerError, SchemaError, known_error

# Deliberately exact: a new server tool can never silently become callable.
READ_TOOLS = frozenset(
    {
        "get_accounts",
        "get_portfolio",
        "get_equity_positions",
        "get_option_positions",
        "get_crypto_positions",
        "get_equity_orders",
        "get_option_orders",
        "get_crypto_orders",
        "get_currency_pairs",
        "search",
        "get_option_chains",
        "get_option_instruments",
        "get_watchlists",
        "get_watchlist_items",
        "get_option_watchlist",
    }
)


class ToolClient:
    def __init__(self, client):
        self.client = client
        self.schemas: dict[str, dict] = {}
        self.fingerprint = ""

    async def discover(self) -> None:
        schemas = {}
        cursor = None
        seen = set()
        while True:
            result = await self.client.list_tools(cursor=cursor, cache_mode="bypass")
            for tool in result.tools:
                if tool.name not in READ_TOOLS:
                    continue
                schema = tool.input_schema
                validator = validators.validator_for(schema)
                validator.check_schema(schema)
                if tool.name in schemas:
                    raise SchemaError("Duplicate tool name in broker discovery")
                schemas[tool.name] = schema
            cursor = result.next_cursor
            if not cursor:
                break
            if cursor in seen or len(seen) > 100:
                raise SchemaError("Invalid tool discovery pagination")
            seen.add(cursor)
        self.schemas = schemas
        self.fingerprint = hashlib.sha256(json.dumps(schemas, sort_keys=True).encode()).hexdigest()

    def require(self, names) -> None:
        missing = set(names) - self.schemas.keys()
        if missing:
            raise SchemaError("Broker is missing required tools: " + ", ".join(sorted(missing)))

    def arguments(
        self,
        name: str,
        values: dict[str, Any],
        aliases: dict[str, tuple[str, ...]] | None = None,
        required_keys: tuple[str, ...] = (),
    ) -> dict:
        """Map explicitly supported field aliases; never guess required values."""
        self.require([name])
        properties = self.schemas[name].get("properties", {})
        result = {}
        for key, value in values.items():
            if value is None:
                continue
            candidates = (key,) + (aliases or {}).get(key, ())
            destination = next(
                (candidate for candidate in candidates if candidate in properties), None
            )
            if destination:
                # Official catalogs use CSV strings for contract IDs and expirations;
                # older supported schemas use arrays for the same fields.
                if (
                    key in {"ids", "expiration_dates", "symbols"}
                    and isinstance(value, list)
                    and properties[destination].get("type") == "string"
                ):
                    value = ",".join(value)
                result[destination] = value
        if not set(required_keys) <= result.keys():
            raise SchemaError(f"Live schema for {name} cannot preserve required account scope")
        self.validate(name, result)
        return result

    def validate(self, name: str, arguments: dict) -> None:
        if name not in READ_TOOLS:
            raise SchemaError("rhtop only permits dashboard read tools")
        self.require([name])
        schema = self.schemas[name]
        validator = validators.validator_for(schema)(schema, format_checker=FormatChecker())
        if next(validator.iter_errors(arguments), None) is not None:
            raise SchemaError(f"Payload does not match the live schema for {name}")

    async def call(self, name: str, arguments: dict) -> Any:
        self.validate(name, arguments)
        attempts = 3
        for attempt in range(attempts):
            try:
                result = await self.client.call_tool(name, arguments, read_timeout_seconds=45)
                if result.is_error:
                    raise BrokerError(f"Robinhood tool {name} returned an error")
                value = result.structured_content
                if value is None:
                    texts = [
                        item.text
                        for item in result.content
                        if getattr(item, "type", None) == "text"
                    ]
                    try:
                        value = json.loads("\n".join(texts))
                    except (ValueError, TypeError) as exc:
                        raise SchemaError(
                            f"{name} returned an unsupported response format"
                        ) from exc
                if isinstance(value, dict) and (
                    value.get("error") or value.get("is_error") is True
                ):
                    raise BrokerError(f"Robinhood tool {name} returned an error")
                return value
            except (TimeoutError, OSError, httpx2.TransportError) as exc:
                if attempt + 1 == attempts:
                    raise BrokerError(f"Connection failed during {name}") from exc
                await asyncio.sleep(2**attempt)
            except MCPError as exc:
                raise BrokerError(f"Robinhood tool {name} failed (MCP code {exc.code})") from exc
        raise BrokerError(f"Robinhood tool {name} failed")


@asynccontextmanager
async def connect(config: ConnectionConfig, vault: TokenVault, on_authorize=None):
    callback = OAuthCallback(config.oauth_port, on_authorize)
    auth = OAuthClientProvider(
        server_url=config.mcp_url,
        client_metadata=OAuthClientMetadata(
            client_name="rhtop (read-only dashboard)",
            redirect_uris=[callback.redirect_uri],
            token_endpoint_auth_method="none",  # noqa: S106 -- OAuth public-client method
            grant_types=["authorization_code", "refresh_token"],
        ),
        storage=vault,
        redirect_handler=callback.redirect,
        callback_handler=callback.receive,
    )
    try:
        async with httpx2.AsyncClient(
            auth=auth, timeout=httpx2.Timeout(45, connect=15), follow_redirects=False
        ) as http:
            transport = streamable_http_client(config.mcp_url, http_client=http)
            async with Client(transport, cache=None) as client:
                broker = ToolClient(client)
                await broker.discover()
                yield broker
    except BaseExceptionGroup as exc:
        error = known_error(exc)
        if error is not None:
            raise error from None
        raise
    finally:
        await callback.close()
