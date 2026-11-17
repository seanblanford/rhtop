"""Read-only list selector and contents, isolated from account polling failures."""

import asyncio

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import OptionList, Select, Static

from .formatting import clean, panel_title


class Watchlists(Vertical):
    def __init__(self):
        super().__init__(id="watchlists", classes="panel")
        self.reader = None
        self.lists = ()

    def compose(self) -> ComposeResult:
        yield Select([], prompt="Choose a watchlist", id="watchlist-select", compact=True)
        yield Static("Loading watchlists…", id="watchlist-status", markup=False)
        yield OptionList(id="watchlist-items")

    def on_mount(self) -> None:
        self.border_title = panel_title(
            5, "Watchlists", self.app.get_css_variables()["footer-key-foreground"]
        )
        self.border_subtitle = "read only"

    def reload(self, reader) -> None:
        self.reader = reader
        self.load_lists()

    def status(self, message: str) -> None:
        self.query_one("#watchlist-status", Static).update(message)

    @work(group="watchlist-lists", exclusive=True, exit_on_error=False)
    async def load_lists(self) -> None:
        reader = self.reader
        try:
            lists = await reader.lists()
            if reader is not self.reader:
                return
            selector = self.query_one(Select)
            previous = selector.value
            if lists != self.lists:
                self.lists = lists
                selector.set_options([(clean(row.name), row.identifier) for row in lists])
            selected = next((row for row in lists if row.identifier == previous), None)
            value = (
                selected.identifier if selected else lists[0].identifier if lists else Select.BLANK
            )
            if selector.value != value:
                selector.value = value
            else:
                self.load_items()
            if not lists:
                self.query_one(OptionList).clear_options()
                self.status("No watchlists returned")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.status("Watchlists unavailable · r to retry; previous data may be stale")

    @on(Select.Changed, "#watchlist-select")
    def selected(self, event: Select.Changed) -> None:
        event.stop()
        self.load_items()

    @work(group="watchlist-items", exclusive=True, exit_on_error=False)
    async def load_items(self) -> None:
        value = self.query_one(Select).value
        selected = next((row for row in self.lists if row.identifier == value), None)
        options = self.query_one(OptionList)
        options.clear_options()
        if selected is None or self.reader is None:
            return
        reader = self.reader
        self.status("Loading…")
        try:
            rows = await reader.items(selected)
            if reader is not self.reader or self.query_one(Select).value != value:
                return
            options.add_options([Text(clean(row)) for row in rows])
            notice = " · single-leg options only" if selected.options else ""
            self.status(f"{len(rows)} items · {clean(selected.owner)} · read only{notice}")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.status("Items unavailable · r to retry")

    @on(OptionList.OptionSelected, "#watchlist-items")
    def inspect(self, event: OptionList.OptionSelected) -> None:
        event.stop()
