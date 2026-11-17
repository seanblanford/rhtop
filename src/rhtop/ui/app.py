"""btop-style dashboard with a single long-lived, reconnecting read worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Footer, Input, Static

from ..assets import AssetHistory
from ..auth import TokenVault
from ..errors import RhtopError, known_error
from ..models import Account, Snapshot
from ..settings import LAYOUTS, Settings
from .asset_picker import AssetPicker
from .clock import HeaderClock
from .dialogs import AccountDialog, AssetDialog, AuthorizationDialog, DetailDialog, InfoDialog
from .formatting import account_text, order_cells, panel_title, position_cells
from .layout import arrange
from .watchlists import Watchlists

HELP = """Tab / Shift+Tab     Focus next / previous panel
↑/↓ or j/k          Move through rows
Enter              Inspect selected row (read only)
/                  Filter both tables by symbol, asset, side, or state
Esc                Clear filter / close dialog
s / S              Cycle sort column / reverse sort
Click header       Sort by that column
m or Ctrl+h        Toggle *** for financial values and identifiers
a                  Select an active account (MCP / Agentic is the default)
r                  Refresh / retry connection
p                  Pause / resume polling
1 / 2 / 3 / 4 / 5  Toggle overview / positions / orders / assets / watchlists
Watchlists         Choose a list to view its contents (read only)
Assets column      Pick Crypto / Options / Equities; Enter to search
Assets results     Enter to inspect/save; options first choose an underlying
Recent assets      Saved equities/contracts reload on the next launch
l                  Cycle classic / mirrored / stacked layouts
?                  This help
q / Ctrl+c / Ctrl+q Quit (Ctrl+c works in inputs and dialogs)

Privacy starts ON each launch. Revealing is session-only.
Symbols, sides, states, dates, and row counts remain visible.
Layout, panels, refresh interval, and sort direction are saved.
Account selection is saved only in the encrypted credential vault.
Unknown values show —. Partial/failed reads are called out below.
There are no trading actions in rhtop."""


class DashboardTable(DataTable):
    BINDINGS = [Binding("j", "cursor_down", show=False), Binding("k", "cursor_up", show=False)]


class RhtopApp(App):
    TITLE = "rhtop"
    CSS_PATH = "dashboard.tcss"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", show=False, priority=True),
        Binding("ctrl+q", "quit", show=False, priority=True),
        Binding("m", "privacy", "Mask"),
        Binding("ctrl+h", "privacy", show=False, priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("p", "pause", "Pause"),
        Binding("a", "accounts", "Account"),
        Binding("slash", "filter", "Filter"),
        Binding("s", "sort", "Sort"),
        Binding("S", "reverse", show=False),
        Binding("1", "panel('account')", show=False),
        Binding("2", "panel('positions')", show=False),
        Binding("3", "panel('orders')", show=False),
        Binding("4", "panel('assets')", show=False),
        Binding("5", "panel('watchlists')", show=False),
        Binding("l", "layout", "Layout"),
        Binding("question_mark", "help", "Help"),
        Binding("escape", "clear_filter", show=False),
    ]

    def __init__(
        self,
        reader_context,
        settings: Settings,
        settings_path: Path,
        vault: TokenVault | None = None,
        demo: bool = False,
    ):
        super().__init__()
        self.reader_context = reader_context
        self.settings, self.settings_path = settings, settings_path
        self.vault, self.demo = vault, demo
        self.history = AssetHistory(vault, settings_path.with_name("demo-recents.json"))
        self.current_reader = None
        self.asset_request = ("crypto", "", False)
        self.hidden = True
        self.paused = False
        self.refresh_requested = True
        self.stale = False
        self.snapshot: Snapshot | None = None
        self.accounts: list[Account] = []
        self.selected_number = vault.preferred_account() if vault else None
        self.wake = asyncio.Event()
        self.connection_status = "Connecting…" if not demo else "Loading offline demo…"
        self.preference_error = False
        self.sort_columns = {"positions": 0, "orders": 6}
        self.displayed_rows: dict[str, list] = {"positions": [], "orders": []}

    def _fatal_error(self) -> None:
        # Textual's default traceback includes locals, potentially including credentials.
        # Keep the original exception for run_test(), but never print it to a user.
        self.panic("rhtop stopped after an unexpected UI error. No diagnostic payload was printed.")

    def get_driver_class(self):
        driver_class = super().get_driver_class()
        if sys.platform != "win32":
            from textual.drivers.linux_driver import LinuxDriver

            from .terminal import ArrowPointerDriver

            if driver_class is LinuxDriver:
                return ArrowPointerDriver
        return driver_class

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static(id="topline")
            yield Static(id="status", markup=False)
            yield HeaderClock()
        with Container(id="workspace"):
            with VerticalScroll(id="account", classes="panel", can_focus=True):
                overview = Static(id="account-content")
                # Preserve each clickable span's own color, including the green account ID.
                overview.auto_links = False
                yield overview
            for name in ("positions", "orders"):
                with Vertical(id=name, classes="panel"):
                    yield DashboardTable(id=f"{name}-table", cursor_type="row", zebra_stripes=False)
                    yield Static(
                        "Loading orders…", id=f"{name}-empty", classes="empty", markup=False
                    )
            yield AssetPicker(self.history)
            yield Watchlists()
        yield Input(
            placeholder="Filter symbols, assets, sides, states…  Esc clear",
            id="filter",
            compact=True,
        )
        yield Footer(compact=True)

    def on_mount(self) -> None:
        self.query_one("#filter").display = False
        self.query_one("#positions-table", DataTable).add_columns(
            "Symbol", "Asset", "Quantity", "Avg price", "Value", "P/L"
        )
        self.query_one("#orders-table", DataTable).add_columns(
            "Symbol", "Asset", "Side", "State", "Quantity", "Price", "Created"
        )
        self.apply_layout()
        self.render_data()
        self.query_one("#positions-table").focus()
        self.poll()

    def save_settings(self) -> None:
        try:
            self.settings.save(self.settings_path)
            self.preference_error = False
        except OSError:
            self.preference_error = True
        self.render_status()

    def authorization(self, url: str) -> None:
        self.connection_status = "Waiting for authorization · open the URL manually"
        self.render_status()
        self.push_screen(AuthorizationDialog(url))

    async def wait_for_refresh(self, seconds: float | None = None) -> None:
        try:
            if seconds is None:
                await self.wake.wait()
            else:
                await asyncio.wait_for(self.wake.wait(), seconds)
        except TimeoutError:
            pass
        self.wake.clear()

    @work(exclusive=True, exit_on_error=False)
    async def poll(self) -> None:
        delay = 5
        while True:
            try:
                async with self.reader_context(self.authorization) as reader:
                    if isinstance(self.screen, AuthorizationDialog):
                        self.pop_screen()
                    self.current_reader = reader
                    self.query_one(Watchlists).reload(reader.watchlists)
                    self.browse_assets(*self.asset_request)
                    self.accounts = await reader.accounts()
                    eligible = [account for account in self.accounts if account.agentic]
                    if self.selected_number is None and len(eligible) == 1:
                        self.selected_number = eligible[0].number
                    while True:
                        if self.paused and not self.refresh_requested:
                            await self.wait_for_refresh()
                            continue
                        account = next(
                            (a for a in self.accounts if a.number == self.selected_number), None
                        )
                        if account is None:
                            self.snapshot = None
                            self.connection_status = (
                                "Select an account with a · all views read only"
                            )
                            self.render_data()
                            if not isinstance(self.screen, AccountDialog):
                                self.action_accounts()
                            await self.wait_for_refresh()
                            continue
                        self.connection_status = "Refreshing…"
                        self.render_status()
                        self.refresh_requested = False
                        self.query_one(Watchlists).reload(reader.watchlists)
                        result = await reader.snapshot(account)
                        # A switch during an in-flight read must not paint the old account.
                        if account.number == self.selected_number:
                            self.snapshot = result
                            self.stale = False
                            self.connection_status = (
                                "Connected" if not self.demo else "Offline demo"
                            )
                            delay = 5
                            self.render_data()
                            if self.asset_request[0] == "crypto" and not self.paused:
                                self.browse_assets(*self.asset_request)
                        await self.wait_for_refresh(
                            None if self.paused else self.settings.poll_seconds
                        )
                        # Refresh the chooser as accounts can be added/removed server-side.
                        self.accounts = await reader.accounts()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = known_error(exc)
                self.connection_status = (
                    str(error)
                    if error
                    else "Connection failed. Check network / authorization; r to retry."
                )
                self.connection_status += f" · retry in {delay}s"
                self.stale = True
                self.render_status()
                await self.wait_for_refresh(None if self.paused else delay)
                delay = min(delay * 2, 60)
            finally:
                self.current_reader = None
                panel = self.query_one(Watchlists)
                panel.reader = None
                panel.status("Disconnected · previous data may be stale")

    def render_status(self) -> None:
        status = self.connection_status
        if self.stale:
            status += " · STALE: showing last successful read" if self.snapshot else " · no data"
        if self.paused:
            status += " · PAUSED"
        if self.preference_error:
            status += " · could not save preferences"
        if self.snapshot and self.snapshot.notices:
            status += " · " + "; ".join(self.snapshot.notices)
        dot_color = (
            "#ffcc00"
            if self.paused
            else "#00ff06"
            if self.connection_status == "Connected" and not self.stale
            else "#ff8d28"
        )
        status_widget = self.query_one("#status", Static)
        status_widget.update(Text.assemble(("●", dot_color), f" {status}"))
        tooltip = status
        if self.snapshot and self.snapshot.updated:
            tooltip += "\nLast updated: " + self.snapshot.updated.astimezone().strftime(
                "%Y-%m-%d %H:%M:%S %Z"
            )
        status_widget.tooltip = tooltip
        top = Text(" rhtop", style="bold #7dd3a8")
        top.append("   ROBINHOOD MCP", style="#8a959e")
        top.append("   DEMO" if self.demo else "", style="#e9bd73")
        top.append("   read only", style="#7dd3a8")
        top.append("   *** hidden" if self.hidden else "   values visible", style="#e9bd73")
        self.query_one("#topline", Static).update(top)

    def render_data(self) -> None:
        key_color = self.get_css_variables()["footer-key-foreground"]
        self.query_one("#account").border_title = panel_title(1, "Overview", key_color)
        self.query_one("#account-content", Static).update(
            account_text(self.snapshot, self.hidden, self.demo)
        )
        term = self.query_one("#filter", Input).value.casefold().strip()
        for name, formatter in (("positions", position_cells), ("orders", order_cells)):
            table = self.query_one(f"#{name}-table", DataTable)
            rows = list(getattr(self.snapshot, name, ()))
            # Filtering never searches masked financial data or private identifiers.
            rows = [
                row
                for row in rows
                if term
                in " ".join(
                    str(getattr(row, key, "")) for key in ("symbol", "asset", "side", "state")
                ).casefold()
            ]
            fields = (
                ("symbol", "asset", "quantity", "average_price", "market_value", "unrealized_pnl")
                if name == "positions"
                else ("symbol", "asset", "side", "state", "quantity", "price", "created")
            )
            field = fields[self.sort_columns[name]]
            present = [row for row in rows if getattr(row, field) is not None]
            missing = [row for row in rows if getattr(row, field) is None]
            rows = (
                sorted(
                    present,
                    key=lambda row: getattr(row, field),
                    reverse=self.settings.sort_descending,
                )
                + missing
            )
            previous = self.displayed_rows[name]
            selected = (
                previous[table.cursor_row]
                if previous and table.cursor_row < len(previous)
                else None
            )
            table.clear()
            for index, row in enumerate(rows):
                table.add_row(*[Text(cell) for cell in formatter(row, self.hidden)], key=str(index))
            if selected in rows:
                table.move_cursor(row=rows.index(selected))
            self.displayed_rows[name] = rows
            self.query_one(f"#{name}").border_title = panel_title(
                2 if name == "positions" else 3, f"{name.title()} · {len(rows)}", key_color
            )
            self.query_one(
                f"#{name}"
            ).border_subtitle = f"{fields[self.sort_columns[name]].replace('_', ' ')} {'↓' if self.settings.sort_descending else '↑'}"
            empty = self.query_one(f"#{name}-empty", Static)
            empty.display = not rows
            empty.update(
                "No matching rows"
                if term
                else ("No rows returned" if self.snapshot else "Loading positions…")
            )
            table.display = True
        self.render_status()

    def apply_layout(self, width: int | None = None) -> None:
        arrange(
            self.query_one("#workspace"),
            self.settings.panels,
            self.settings.layout,
            self.size.width if width is None else width,
        )

    @work(group="assets", exclusive=True, exit_on_error=False)
    async def browse_assets(self, kind: str, query: str, underlying: bool = False) -> None:
        self.asset_request = (kind, query, underlying)
        picker = self.query_one(AssetPicker)
        reader = self.current_reader
        if reader is None:
            picker.query_one("#asset-status", Static).update("Loading assets…")
            return
        try:
            results = await reader.assets.browse(kind, query, underlying=underlying)
            if self.asset_request == (kind, query, underlying) and picker.kind == kind:
                picker.show_results(results)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = known_error(exc)
            picker.query_one("#asset-status", Static).update(
                (str(error) if error else "Asset lookup failed. Press Enter to retry.")
                + (" · previous catalog may be stale" if picker.results else "")
            )

    @on(AssetPicker.SearchRequested)
    def asset_search(self, event: AssetPicker.SearchRequested) -> None:
        same_underlying = (
            event.kind == "option"
            and self.asset_request[2]
            and event.query.strip()
            and event.query.split()[0].upper() == self.asset_request[1].split()[0].upper()
        )
        self.browse_assets(event.kind, event.query, bool(same_underlying))

    @on(AssetPicker.AssetSelected)
    def asset_selected(self, event: AssetPicker.AssetSelected) -> None:
        asset = event.asset
        if asset.underlying:
            field = self.query_one("#asset-query", Input)
            field.value = asset.symbol
            field.placeholder = "SYMBOL [YYYY-MM-DD] [call|put] [strike]"
            self.browse_assets("option", asset.symbol, True)
            return
        try:
            self.history.remember(asset)
        except (OSError, RhtopError):
            self.preference_error = True
        self.query_one(AssetPicker).update_recents()
        self.push_screen(AssetDialog(asset, self.hidden))
        self.render_status()

    def on_resize(self, event: events.Resize) -> None:
        if self.is_mounted and self.query("#workspace"):
            self.apply_layout(event.size.width)

    def action_privacy(self) -> None:
        self.hidden = not self.hidden
        if isinstance(self.screen, (DetailDialog, AccountDialog, AssetDialog)):
            self.pop_screen()
        self.render_data()

    def action_refresh(self) -> None:
        self.refresh_requested = True
        self.wake.set()
        if self.current_reader:
            self.browse_assets(*self.asset_request)
            self.query_one(Watchlists).reload(self.current_reader.watchlists)

    def action_pause(self) -> None:
        self.paused = not self.paused
        self.wake.set()
        self.render_status()

    def action_accounts(self) -> None:
        if self.accounts and not isinstance(self.screen, AccountDialog):
            self.push_screen(AccountDialog(self.accounts, self.hidden), self.select_account)

    def action_copy_account_id(self) -> None:
        if self.snapshot is not None:
            self.copy_to_clipboard(self.snapshot.account.number)
            self.notify("Account ID copy requested.", title="Clipboard", timeout=2)

    def select_account(self, number: str | None) -> None:
        if number is None:
            return
        if self.vault:
            try:
                self.vault.select_account(number)
            except (OSError, RhtopError):
                self.preference_error = True
        self.selected_number = number
        self.snapshot = None
        self.refresh_requested = True
        self.render_data()
        self.wake.set()

    def action_filter(self) -> None:
        self.query_one("#filter").display = True
        self.query_one("#filter").focus()

    def action_clear_filter(self) -> None:
        self.query_one("#filter", Input).value = ""
        self.query_one("#filter").display = False
        self.focus_dashboard()

    def focus_dashboard(self) -> None:
        for name in ("positions", "orders"):
            if name in self.settings.panels:
                self.query_one(f"#{name}-table").focus()
                return
        if "account" in self.settings.panels:
            self.query_one("#account").focus()
        elif "assets" in self.settings.panels:
            self.query_one("#asset-kind").focus()
        else:
            self.query_one("#watchlist-select").focus()

    @on(Input.Changed, "#filter")
    def filter_changed(self) -> None:
        self.render_data()

    @on(DataTable.RowSelected)
    def inspect_row(self, event: DataTable.RowSelected) -> None:
        name = "positions" if event.data_table.id == "positions-table" else "orders"
        rows = self.displayed_rows[name]
        if event.cursor_row < len(rows):
            self.push_screen(DetailDialog(rows[event.cursor_row], self.hidden))

    @on(DataTable.HeaderSelected)
    def header_selected(self, event: DataTable.HeaderSelected) -> None:
        name = "positions" if event.data_table.id == "positions-table" else "orders"
        if self.sort_columns[name] == event.column_index:
            self.settings.sort_descending = not self.settings.sort_descending
        self.sort_columns[name] = event.column_index
        self.save_settings()
        self.render_data()

    def action_sort(self) -> None:
        name = "orders" if self.focused and self.focused.id == "orders-table" else "positions"
        self.sort_columns[name] = (self.sort_columns[name] + 1) % (7 if name == "orders" else 6)
        self.render_data()

    def action_reverse(self) -> None:
        self.settings.sort_descending = not self.settings.sort_descending
        self.save_settings()
        self.render_data()

    def action_panel(self, name: str) -> None:
        if name in self.settings.panels:
            if len(self.settings.panels) == 1:
                return
            self.settings.panels.remove(name)
        else:
            self.settings.panels.append(name)
        self.apply_layout()
        self.save_settings()
        self.focus_dashboard()

    def action_layout(self) -> None:
        self.settings.layout = LAYOUTS[(LAYOUTS.index(self.settings.layout) + 1) % len(LAYOUTS)]
        self.apply_layout()
        self.save_settings()

    def action_help(self) -> None:
        self.push_screen(InfoDialog("rhtop · keys", HELP))
