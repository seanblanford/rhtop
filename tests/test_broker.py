from decimal import Decimal
from types import SimpleNamespace

import pytest
from mcp import Client
from mcp.server import MCPServer

from rhtop.broker.client import READ_TOOLS, ToolClient
from rhtop.broker.dashboard import DashboardReader
from rhtop.broker.parsing import accounts, decimal, records
from rhtop.errors import BrokerError, SchemaError


async def test_official_sdk_reads_and_excludes_mutations():
    server = MCPServer("offline-test-broker")
    mutations = []

    @server.tool()
    async def get_accounts() -> dict:
        return {"data": {"accounts": [{"account_number": "MCP1", "agentic_allowed": True}]}}

    @server.tool()
    async def place_equity_order() -> dict:
        mutations.append(True)
        return {}

    async with Client(server, cache=None) as client:
        broker = ToolClient(client)
        await broker.discover()
        assert list(broker.schemas) == ["get_accounts"]
        assert accounts(await broker.call("get_accounts", {}))[0].number == "MCP1"
        for name in ("place_equity_order", "cancel_equity_order", "preview_order", "get_unknown"):
            broker.schemas[name] = {"type": "object"}
            with pytest.raises(SchemaError, match="only permits"):
                await broker.call(name, {})
    assert mutations == []
    assert len(READ_TOOLS) == 15


class FixtureSession:
    def __init__(self):
        scoped = {
            "type": "object",
            "properties": {"account_number": {"type": "string"}},
            "required": ["account_number"],
            "additionalProperties": False,
        }
        self.schemas = {name: scoped for name in READ_TOOLS if "crypto" not in name}
        self.schemas["get_accounts"] = {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
        self.values = {
            "get_accounts": {
                "accounts": [
                    {"account_number": "PERSONAL", "agentic_allowed": False},
                    {"account_number": "MCP1", "agentic_allowed": True},
                ]
            },
            "get_portfolio": {
                "total_value": "1500",
                "cash": "200",
                "buying_power": {"buying_power": "400"},
            },
            "get_equity_positions": {
                "positions": [
                    {
                        "account_number": "MCP1",
                        "symbol": "TEST",
                        "quantity": "2",
                        "average_buy_price": "10",
                    },
                    {"account_number": "PERSONAL", "symbol": "PRIVATE", "quantity": "99"},
                ]
            },
            "get_equity_orders": {
                "orders": [{"symbol": "TEST", "state": "queued", "quantity": "1"}]
            },
            "get_option_positions": {"positions": []},
            "get_option_orders": {"orders": []},
        }
        self.calls = []

    async def list_tools(self, **kwargs):
        return SimpleNamespace(
            tools=[SimpleNamespace(name=k, input_schema=v) for k, v in self.schemas.items()],
            next_cursor=None,
        )

    async def call_tool(self, name, arguments, **kwargs):
        self.calls.append((name, arguments))
        value = self.values[name]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(is_error=False, structured_content=value)


async def fixture_reader():
    session = FixtureSession()
    broker = ToolClient(session)
    await broker.discover()
    reader = DashboardReader(broker)
    account = next(item for item in await reader.accounts() if item.agentic)
    return session, broker, reader, account


async def test_account_scope_missing_values_and_actual_buying_power():
    session, _, reader, account = await fixture_reader()
    result = await reader.snapshot(account)
    assert result.total_value == Decimal("1500")
    assert result.buying_power == Decimal("400")  # display the buying power supplied by the broker
    assert len(result.positions) == 1
    assert result.positions[0].symbol == "TEST"
    assert result.positions[0].market_value is None
    assert result.orders[0].price is None
    for tool, arguments in session.calls:
        if tool != "get_accounts":
            assert arguments["account_number"] == "MCP1"


async def test_pagination_and_read_failure_are_visible():
    session, _, reader, account = await fixture_reader()
    session.values["get_equity_positions"]["next_cursor"] = "synthetic-next-page"
    session.values["get_equity_orders"] = BrokerError("safe read failure")
    result = await reader.snapshot(account)
    assert any("partial" in notice for notice in result.notices)
    assert any("read failed" in notice for notice in result.notices)
    assert result.orders == ()


async def test_unscoped_collection_does_not_mix_accounts():
    session, broker, reader, account = await fixture_reader()
    broker.schemas["get_equity_positions"] = {"type": "object", "properties": {}}
    session.values["get_equity_positions"] = {
        "positions": [{"symbol": "PRIVATE", "quantity": "100"}]
    }
    result = await reader.snapshot(account)
    assert result.positions == ()
    assert any("equity positions: read failed" in notice for notice in result.notices)


async def test_unavailable_selected_account_never_falls_back():
    session, _, reader, account = await fixture_reader()
    session.values["get_accounts"]["accounts"][1]["account_number"] = "MCP2"
    with pytest.raises(SchemaError, match="no longer"):
        await reader.snapshot(account)
    assert not any(name == "get_portfolio" for name, _ in session.calls)


async def test_required_account_scope_is_not_dropped():
    session, broker, reader, account = await fixture_reader()
    broker.schemas["get_portfolio"] = {"type": "object", "properties": {}}
    with pytest.raises(SchemaError, match="account scope"):
        await reader.snapshot(account)
    assert not any(name == "get_portfolio" for name, _ in session.calls)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "bad", True])
def test_bad_financial_data_is_not_rendered(value):
    with pytest.raises(SchemaError):
        decimal({"quantity": value}, "quantity")


def test_envelopes_and_eligible_accounts():
    assert records({"result": {"data": {"results": []}}}, "positions") == []
    assert not accounts({"accounts": [{"account_number": "PERSONAL", "agentic_allowed": False}]})[
        0
    ].agentic
    with pytest.raises(SchemaError):
        accounts({"accounts": []})
