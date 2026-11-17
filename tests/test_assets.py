from types import SimpleNamespace

import pytest
from test_ui import demo_context, ready
from textual.widgets import Input, OptionList, Select

from rhtop.assets import Asset, AssetHistory
from rhtop.auth import TokenVault
from rhtop.broker.assets import AssetReader
from rhtop.broker.client import ToolClient
from rhtop.errors import SchemaError
from rhtop.settings import Settings
from rhtop.ui.app import RhtopApp
from rhtop.ui.asset_picker import AssetPicker
from rhtop.ui.dialogs import AssetDialog


class CatalogSession:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments, **kwargs):
        self.calls.append((name, arguments))
        if name == "get_currency_pairs":
            value = (
                {"results": [{"symbol": "BTC-USD", "name": "Bitcoin"}], "next": "page2"}
                if not arguments.get("cursor")
                else {
                    "results": [
                        {
                            "symbol": "HALT-USD",
                            "name": "Halted",
                            "halted": True,
                            "halted_regions": ["NY", "TX"],
                        }
                    ]
                }
            )
        elif name == "search":
            value = {"results": [{"symbol": "AAPL", "name": "Apple", "instrument_id": "apple-id"}]}
        else:
            value = {
                "instruments": [
                    {
                        "chain_symbol": "AAPL",
                        "expiration_date": "2026-12-18",
                        "strike_price": "250",
                        "type": "call",
                        "id": "option-id",
                        "state": "active",
                        "tradability": "tradable",
                    }
                ]
            }
        return SimpleNamespace(is_error=False, structured_content={"data": value})


def catalog_reader():
    session = CatalogSession()
    broker = ToolClient(session)
    broker.schemas = {
        "get_currency_pairs": {
            "type": "object",
            "properties": {"cursor": {"type": "string"}, "limit": {"type": "integer"}},
        },
        "search": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "asset_type": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        "get_option_instruments": {
            "type": "object",
            "properties": {
                key: {"type": "string"}
                for key in ("chain_symbol", "cursor", "expiration_dates", "type", "strike_price")
            },
            "required": ["chain_symbol"],
        },
    }
    return session, broker, AssetReader(broker)


async def test_complete_crypto_catalog_includes_halted_and_follows_all_pages():
    session, _, reader = catalog_reader()
    result = await reader.browse("crypto")
    assert [asset.symbol for asset in result.rows] == ["BTC-USD", "HALT-USD"]
    assert result.rows[1].title.endswith("🚫 NY TX")
    assert result.rows[1].regions == "NY TX"
    assert session.calls[1][1] == {"limit": 700, "cursor": "page2"}


async def test_crypto_catalog_refuses_to_claim_complete_without_cursor_support():
    _, broker, reader = catalog_reader()
    del broker.schemas["get_currency_pairs"]["properties"]["cursor"]
    with pytest.raises(SchemaError, match="pagination cursor"):
        await reader.browse("crypto")


async def test_equity_search_and_filtered_options_use_schema_supported_arguments():
    session, _, reader = catalog_reader()
    equities = await reader.browse("equity", "Apple")
    assert equities.rows[0].symbol == "AAPL"
    assert session.calls[-1] == (
        "search",
        {"query": "Apple", "asset_type": "instrument", "limit": 20},
    )
    underlying = await reader.browse("option", "Apple")
    assert underlying.rows[0].underlying
    options = await reader.browse("option", "AAPL 2026-12-18 call 250", underlying=True)
    assert options.rows[0].identifier == "option-id"
    assert session.calls[-1][1] == {
        "chain_symbol": "AAPL",
        "expiration_dates": "2026-12-18",
        "type": "call",
        "strike_price": "250",
    }


def test_live_recents_are_encrypted_deduplicated_and_reload(tmp_path):
    vault = TokenVault(tmp_path, "test", "a long synthetic passphrase")
    history = AssetHistory(vault, tmp_path / "unused.json")
    asset = Asset("equity", "PRIVATE_INTEREST", "Synthetic", "synthetic-id")
    history.remember(asset)
    history.remember(asset)
    assert b"PRIVATE_INTEREST" not in vault.path.read_bytes()
    reopened = AssetHistory(
        TokenVault(tmp_path, "test", "a long synthetic passphrase"), tmp_path / "unused.json"
    )
    assert reopened.for_kind("equity") == [asset]
    assert not (tmp_path / "unused.json").exists()


async def test_asset_picker_defaults_crypto_search_saves_equities_and_options_on_restart(tmp_path):
    path = tmp_path / "settings.json"
    app = RhtopApp(demo_context, Settings(), path, demo=True)
    async with app.run_test(size=(150, 42)) as pilot:
        await ready(app, pilot)
        await pilot.pause()
        picker = app.query_one(AssetPicker)
        assert picker.kind == "crypto"
        assert any(asset.title.endswith("🚫 ALL") for asset in picker.results)
        app.query_one("#asset-kind", Select).value = "equity"
        await pilot.pause()
        field = app.query_one("#asset-query", Input)
        field.value = "Apple"
        field.focus()
        await pilot.press("enter")
        await pilot.pause()
        results = app.query_one("#asset-results", OptionList)
        results.focus()
        await pilot.press("enter")
        assert isinstance(app.screen, AssetDialog)
        await pilot.press("escape")
        assert app.history.for_kind("equity")[0].symbol == "AAPL"
        app.query_one("#asset-kind", Select).value = "option"
        await pilot.pause()
        field.value = "Apple"
        field.focus()
        await pilot.press("enter")
        await pilot.pause()
        results.focus()
        await pilot.press("enter")  # choose underlying
        await pilot.pause()
        assert len(picker.results) == 2
        results.focus()
        await pilot.press("enter")  # choose contract
        assert isinstance(app.screen, AssetDialog)
        await pilot.press("m")
        assert not isinstance(app.screen, AssetDialog)
        assert len(app.history.for_kind("option")) == 1
    restarted = RhtopApp(demo_context, Settings(), path, demo=True)
    assert len(restarted.history.for_kind("equity")) == 1
    assert len(restarted.history.for_kind("option")) == 1
    assert restarted.hidden
