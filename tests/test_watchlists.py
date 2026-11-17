from contextlib import asynccontextmanager

import pytest
from test_broker import FixtureSession
from test_ui import demo_context, ready
from textual.widgets import OptionList, Select, Static

from rhtop.broker.client import ToolClient
from rhtop.broker.watchlists import WatchlistReader
from rhtop.errors import SchemaError
from rhtop.settings import Settings
from rhtop.ui.app import RhtopApp


async def watchlist_reader():
    session = FixtureSession()
    session.schemas = {
        name: {"type": "object", "properties": {}, "additionalProperties": False}
        for name in ("get_watchlists", "get_option_watchlist")
    }
    session.schemas["get_watchlist_items"] = {
        "type": "object",
        "properties": {"list_id": {"type": "string"}},
        "required": ["list_id"],
        "additionalProperties": False,
    }
    session.values = {
        "get_watchlists": {
            "data": {
                "watchlists": [
                    {"id": "stocks", "display_name": "Stocks", "owner_type": "custom"},
                    {
                        "id": "options",
                        "display_name": "Options",
                        "allowed_object_types": ["option_strategy"],
                    },
                ]
            }
        },
        "get_watchlist_items": {
            "data": {
                "items": [
                    {"symbol": "AAPL", "object_type": "instrument", "object_id": "private-id"},
                    {"object_type": "futures", "object_id": "private-future"},
                ]
            }
        },
        "get_option_watchlist": {
            "data": {
                "items": [
                    {
                        "name": "AAPL $200 Call",
                        "position_type": "short",
                        "expiration_date": "2026-12-18",
                    },
                ]
            }
        },
    }
    broker = ToolClient(session)
    await broker.discover()
    return session, broker, WatchlistReader(broker)


async def test_watchlist_reads_preserve_id_and_route_options():
    session, broker, reader = await watchlist_reader()
    stocks, options = await reader.lists()
    assert await reader.items(stocks) == ("AAPL · instrument", "Unknown · futures")
    assert await reader.items(options) == ("AAPL $200 Call · short · 2026-12-18",)
    assert session.calls == [
        ("get_watchlists", {}),
        ("get_watchlist_items", {"list_id": "stocks"}),
        ("get_option_watchlist", {}),
    ]
    for name in (
        "create_watchlist",
        "update_watchlist",
        "add_to_watchlist",
        "remove_from_watchlist",
    ):
        with pytest.raises(SchemaError, match="only permits"):
            await broker.call(name, {})


async def test_watchlist_pagination_cannot_be_silently_lost():
    session, _, reader = await watchlist_reader()
    session.values["get_watchlists"]["data"]["next_cursor"] = "next"
    with pytest.raises(SchemaError, match="pagination cursor"):
        await reader.lists()


async def test_watchlist_grid_selection_refresh_and_toggle(tmp_path):
    app = RhtopApp(demo_context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(170, 42)) as pilot:
        await ready(app, pilot)
        panel = app.query_one("#watchlists")
        assets = app.query_one("#assets")
        assert panel.region.x == assets.region.right
        assert panel.region.y == assets.region.y
        assert str(panel.border_title).endswith("Watchlists")
        selector = app.query_one("#watchlist-select", Select)
        selector.value = "demo-crypto"
        await pilot.pause()
        items = app.query_one("#watchlist-items", OptionList)
        assert items.option_count == 2
        assert "BTC-USD" in str(items.get_option_at_index(0).prompt)
        app.action_refresh()
        await pilot.pause()
        assert selector.value == "demo-crypto"
        app.query_one("#positions-table").focus()
        await pilot.press("5")
        assert not panel.display
        await pilot.press("5")
        assert panel.display
        app.settings.panels = ["watchlists"]
        app.apply_layout()
        app.focus_dashboard()
        await pilot.pause()
        assert app.focused.id == "watchlist-select"
        assert panel.region.width == 170


async def test_watchlist_failure_does_not_break_portfolio(tmp_path):
    from rhtop.demo import DemoReader

    class Reader(DemoReader):
        async def lists(self):
            raise RuntimeError("PRIVATE_PAYLOAD")

    @asynccontextmanager
    async def context(on_authorize):
        yield Reader()

    app = RhtopApp(context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(150, 42)) as pilot:
        await ready(app, pilot)
        status = app.query_one("#watchlist-status", Static).render().plain
        assert "unavailable" in status and "PRIVATE_PAYLOAD" not in status
        assert app.snapshot.positions
