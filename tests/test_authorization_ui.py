import asyncio
from contextlib import asynccontextmanager, contextmanager, redirect_stdout
from io import StringIO

import pytest
from textual.app import SuspendNotSupported
from textual.widgets import Static, TextArea

from rhtop.demo import DemoReader
from rhtop.settings import Settings
from rhtop.ui.app import RhtopApp
from rhtop.ui.dialogs import AuthorizationDialog

URL = "https://robinhood.com/authorize?state=synthetic-state&redirect_uri=http%3A%2F%2F127.0.0.1%3A8766%2Fcallback"


def authorization_app(tmp_path):
    authorized = asyncio.Event()

    @asynccontextmanager
    async def context(on_authorize):
        on_authorize(URL)
        await authorized.wait()
        yield DemoReader()

    return RhtopApp(context, Settings(), tmp_path / "settings.json", demo=True)


@pytest.mark.parametrize("size", [(150, 42), (80, 24)])
async def test_copy_button_and_shortcut_copy_entire_url_without_selection(tmp_path, size):
    app = authorization_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, AuthorizationDialog)
        area = dialog.query_one("#auth-url", TextArea)
        assert area.selected_text == URL
        area.move_cursor((0, 0))  # Copy must work even after deselecting.
        assert not area.selected_text
        await pilot.press("ctrl+y")
        assert app.clipboard == URL
        assert "Copy requested" in str(dialog.query_one("#auth-copy-note", Static).render())
        app.copy_to_clipboard("")
        await pilot.click("#copy-auth-url")
        assert app.clipboard == URL
        assert (
            dialog.query_one("#show-auth-url").region.bottom
            <= dialog.query_one("#dialog").region.bottom
        )
        assert "synthetic-state" not in app.connection_status


async def test_plain_terminal_fallback_outputs_original_url_and_keeps_loop_alive(
    tmp_path, monkeypatch
):
    app = authorization_app(tmp_path)
    suspended = []
    event_loop_ran = asyncio.Event()
    terminal = StringIO()

    @contextmanager
    def suspend():
        suspended.append(True)
        with redirect_stdout(terminal):
            yield
        suspended.append(False)

    def wait_for_enter():
        # Waiting here would deadlock if input() were called on the event loop.
        future = asyncio.run_coroutine_threadsafe(mark_loop_active(), loop)
        future.result(timeout=2)
        return ""

    async def mark_loop_active():
        event_loop_ran.set()

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(app, "suspend", suspend)
    monkeypatch.setattr("builtins.input", wait_for_enter)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t")
        assert suspended == [True, False]
        assert event_loop_ran.is_set()
        output = terminal.getvalue()
        assert URL in output and "Press Enter" in output


async def test_plain_terminal_unavailable_has_login_fallback(tmp_path, monkeypatch):
    app = authorization_app(tmp_path)

    @contextmanager
    def unavailable():
        raise SuspendNotSupported()
        yield  # pragma: no cover

    monkeypatch.setattr(app, "suspend", unavailable)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+t")
        assert "rhtop login" in str(app.screen.query_one("#auth-copy-note", Static).render())
