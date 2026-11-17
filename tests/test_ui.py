import asyncio
from contextlib import asynccontextmanager

import pytest
from rich.text import Text
from textual.widgets import DataTable, Input

from rhtop.demo import DemoReader
from rhtop.settings import Settings
from rhtop.ui.app import RhtopApp
from rhtop.ui.dialogs import DetailDialog
from rhtop.ui.formatting import account_text, detail_text, position_cells


@asynccontextmanager
async def demo_context(on_authorize):
    yield DemoReader()


async def ready(app, pilot):
    for _ in range(30):
        await pilot.pause()
        if app.snapshot:
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"Dashboard failed to load: {app.connection_status}")


async def test_privacy_filter_inspect_and_keys(tmp_path):
    app = RhtopApp(demo_context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(130, 42)) as pilot:
        await ready(app, pilot)
        table = app.query_one("#positions-table", DataTable)
        footer_color = app.query_one("FooterKey").get_component_rich_style("footer-key--key").color
        for name, key in (("account", 1), ("positions", 2), ("orders", 3), ("assets", 4)):
            title = Text.from_markup(app.query_one(f"#{name}").border_title)
            assert title.plain.startswith(str(key))
            assert (
                title.get_style_at_offset(app.console, 0).color.get_truecolor()
                == footer_color.get_truecolor()
            )
        assert Text.from_markup(app.query_one("#account").border_title).plain == "1 Overview"
        assert table.row_count == 4
        assert "***" in [cell.plain for cell in table.get_row_at(0)]
        assert "DEMO0001" not in account_text(app.snapshot, app.hidden, True).plain
        await pilot.press("m")
        assert not app.hidden
        assert "DEMO0001" in account_text(app.snapshot, app.hidden, True).plain
        table.focus()
        await pilot.press("enter")
        assert isinstance(app.screen, DetailDialog)
        await pilot.press("m")
        assert app.hidden and not isinstance(app.screen, DetailDialog)
        await pilot.press("slash", "b", "t", "c")
        assert app.query_one("#filter", Input).value == "btc"
        assert table.row_count == 1 and table.get_row_at(0)[0].plain == "BTC"
        await pilot.press("escape")
        assert table.row_count == 4
        await pilot.press("s", "S", "p")
        assert app.paused
        await pilot.press("p", "question_mark", "escape")
        assert not app.paused


@pytest.mark.parametrize("size", [(140, 45), (80, 24), (55, 18)])
async def test_layouts_toggles_and_resize(tmp_path, size):
    app = RhtopApp(demo_context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=size) as pilot:
        await ready(app, pilot)
        for _ in range(3):
            await pilot.press("l")
            if app.settings.layout == "mirrored":
                overview = app.query_one("#account").region
                assets = app.query_one("#assets").region
                positions = app.query_one("#positions").region
                orders = app.query_one("#orders").region
                assert overview.x == assets.x == positions.right
                assert overview.width == assets.width
                assert overview.bottom == assets.y
                assert positions.x == orders.x == 0
                assert positions.bottom == orders.y
            for key, panel in (
                ("1", "account"),
                ("2", "positions"),
                ("3", "orders"),
                ("4", "assets"),
            ):
                await pilot.press(key)
                assert not app.query_one(f"#{panel}").display
                await pilot.press(key)
                assert app.query_one(f"#{panel}").display
        assert Settings.load(tmp_path / "settings.json") == app.settings
        assert "DEMO0001" not in (tmp_path / "settings.json").read_text()
        await pilot.resize_terminal(150, 42)
        await pilot.pause()
        assert app.query_one("#account").region.width == 27
        assert app.query_one("#positions").region.x == 27
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert app.query_one("#account").region.width == 50
        assert app.query_one("#assets").region.x == 50


async def test_mask_all_sensitive_fields_in_every_view():
    reader = DemoReader()
    snapshot = await reader.snapshot((await reader.accounts())[0])
    for row in snapshot.positions:
        assert position_cells(row, True)[2:] == ("***",) * 4
        assert "$" not in detail_text(row, True).plain
    for row in snapshot.orders:
        assert row.identifier not in detail_text(row, True).plain


async def test_reconnect_and_stale_status_does_not_expose_exception(tmp_path):
    calls = 0

    @asynccontextmanager
    async def flaky_context(on_authorize):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("PRIVATE_BROKER_RESPONSE")
        yield DemoReader()

    app = RhtopApp(flaky_context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert "PRIVATE_BROKER_RESPONSE" not in app.connection_status
        await pilot.press("r")
        await ready(app, pilot)
        assert calls == 2


async def test_refresh_preserves_selected_row(tmp_path):
    app = RhtopApp(demo_context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await ready(app, pilot)
        table = app.query_one("#positions-table", DataTable)
        table.focus()
        await pilot.press("j", "j")
        before = table.get_row_at(table.cursor_row)[0].plain
        await pilot.press("r")
        await pilot.pause()
        assert table.get_row_at(table.cursor_row)[0].plain == before
