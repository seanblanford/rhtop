import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_ui import demo_context, ready
from textual.widgets import Input, OptionList, Static

from rhtop.demo import DemoReader
from rhtop.models import Account
from rhtop.settings import Settings
from rhtop.ui.app import RhtopApp
from rhtop.ui.dialogs import AccountDialog, AuthorizationDialog, InfoDialog
from rhtop.ui.formatting import account_text, sensitive


async def test_mcp_is_default_and_other_accounts_require_explicit_selection(tmp_path):
    class Reader(DemoReader):
        async def accounts(self):
            return [Account("PERSONAL", agentic=False), Account("MCP1")]

    @asynccontextmanager
    async def context(on_authorize):
        yield Reader()

    app = RhtopApp(context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(150, 42)) as pilot:
        await ready(app, pilot)
        assert app.snapshot.account.number == "MCP1"
        await pilot.press("a")
        assert isinstance(app.screen, AccountDialog)
        choices = app.screen.query_one(OptionList)
        choices.highlighted = 0
        await pilot.press("enter")
        await pilot.pause()
        assert app.snapshot.account.number == "PERSONAL"
        assert not app.snapshot.account.agentic


async def test_pause_suppresses_automatic_reads_but_manual_refresh_works(tmp_path):
    calls = 0

    class Reader(DemoReader):
        async def snapshot(self, account):
            nonlocal calls
            calls += 1
            return await super().snapshot(account)

    @asynccontextmanager
    async def context(on_authorize):
        yield Reader()

    app = RhtopApp(context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(150, 42)) as pilot:
        await ready(app, pilot)
        await pilot.press("p")
        before = calls
        await asyncio.sleep(0.05)
        await pilot.pause()
        assert calls == before
        await pilot.press("r")
        await pilot.pause()
        assert calls == before + 1


async def test_refresh_with_help_overlay_and_masking_in_input(tmp_path):
    app = RhtopApp(demo_context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(150, 42)) as pilot:
        await ready(app, pilot)
        await pilot.press("question_mark")
        assert isinstance(app.screen, InfoDialog)
        app.action_refresh()
        await pilot.pause()
        assert app.snapshot and app.connection_status == "Offline demo"
        await pilot.press("m")
        assert not app.hidden
        await pilot.press("escape")
        field = app.query_one("#asset-query", Input)
        field.focus()
        await pilot.press("a", "m", "ctrl+h")
        assert field.value == "am" and app.hidden
        await pilot.press("ctrl+q")
        assert app._exit


async def test_authorization_overlay_updates_without_exposing_url_in_status(tmp_path):
    authorized = asyncio.Event()

    @asynccontextmanager
    async def context(on_authorize):
        on_authorize("https://robinhood.com/authorize?state=synthetic-state")
        await authorized.wait()
        yield DemoReader()

    app = RhtopApp(context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(150, 42)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, AuthorizationDialog)
        assert "synthetic-state" not in app.connection_status
        authorized.set()
        await ready(app, pilot)
        assert not isinstance(app.screen, AuthorizationDialog)


@pytest.mark.parametrize("view", ["dashboard", "input", "help", "account", "authorization"])
async def test_ctrl_c_quits_from_every_view(tmp_path, view):
    app = RhtopApp(demo_context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(150, 42)) as pilot:
        await ready(app, pilot)
        if view == "input":
            app.query_one("#asset-query", Input).focus()
        elif view == "help":
            await pilot.press("question_mark")
        elif view == "account":
            await pilot.press("a")
        elif view == "authorization":
            app.authorization("https://robinhood.com/authorize?state=synthetic-state")
            await pilot.pause()
        await pilot.press("ctrl+c")
        assert app._exit
        assert app.clipboard == ""


@pytest.mark.parametrize("hidden", [True, False])
async def test_account_label_opens_selector_and_green_id_copies_without_revealing_it(
    tmp_path, hidden
):
    app = RhtopApp(demo_context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(150, 42)) as pilot:
        await ready(app, pilot)
        if not hidden:
            await pilot.press("m")
        lines = account_text(app.snapshot, app.hidden, app.demo).plain.splitlines()
        value = sensitive(app.snapshot.account.number, app.hidden)
        line = lines.index(value)
        content = app.query_one("#account-content", Static)
        assert not content.auto_links
        value_offset = account_text(app.snapshot, app.hidden, app.demo).plain.index(value)
        green = (
            account_text(app.snapshot, app.hidden, app.demo)
            .get_style_at_offset(app.console, value_offset)
            .color.get_truecolor()
        )
        assert green == app.console.get_style("#7dd3a8").color.get_truecolor()
        await pilot.click("#account-content", offset=(0, line - 1))
        assert isinstance(app.screen, AccountDialog)
        assert app.screen.accounts == app.accounts
        await pilot.press("escape")
        await pilot.click("#account-content", offset=(0, line))
        assert not isinstance(app.screen, AccountDialog)
        assert app.clipboard == app.snapshot.account.number
        assert app.hidden == hidden
        await pilot.press("a")
        assert isinstance(app.screen, AccountDialog)


@pytest.mark.parametrize("size", [(150, 42), (80, 24), (55, 18)])
async def test_connection_status_is_right_aligned_in_header_without_bottom_row(tmp_path, size):
    app = RhtopApp(demo_context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=size) as pilot:
        await ready(app, pilot)
        title = app.query_one("#topline")
        status = app.query_one("#status", Static)
        clock = app.query_one("#clock", Static)
        assert title.region.y == status.region.y == clock.region.y == 0
        assert clock.region.right == size[0]
        assert status.region.right < clock.region.x
        assert status.region.height == 1
        assert title.region.right <= status.region.x
        assert status.styles.text_align == "right"
        assert app.query_one("#workspace").region.y == 1
        assert app.query_one("#workspace").region.bottom == app.query_one("Footer").region.y
        app.snapshot = replace(app.snapshot, notices=("equity positions: partial (first page)",))
        app.render_status()
        await pilot.pause()
        assert status.region.height == 1
        assert clock.region.right == size[0]
        assert "partial (first page)" in status.tooltip
        assert "Last updated:" in status.tooltip
        assert "updated" not in status.render().plain


async def test_header_clock_ticks_in_local_timezone_while_polling_is_paused(tmp_path, monkeypatch):
    current = [datetime(2026, 11, 15, 13, 0, 0, tzinfo=UTC)]
    monkeypatch.setattr("rhtop.ui.clock.datetime", SimpleNamespace(now=lambda: current[0]))
    app = RhtopApp(demo_context, Settings(), tmp_path / "settings.json", demo=True)
    async with app.run_test(size=(150, 42)) as pilot:
        await ready(app, pilot)
        clock = app.query_one("#clock", Static)
        assert clock.render().plain == current[0].astimezone().strftime("%H:%M:%S %Z")
        await pilot.press("p")
        snapshot = app.snapshot
        current[0] += timedelta(seconds=5)
        await pilot.pause(delay=1.1)
        assert clock.render().plain == current[0].astimezone().strftime("%H:%M:%S %Z")
        assert app.snapshot is snapshot and app.paused
