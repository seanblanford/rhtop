"""Small keyboard-friendly overlays; no raw payload or credential inspector."""

import asyncio

from rich.text import Text
from textual import on
from textual.app import ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList, Static, TextArea

from ..assets import Asset
from ..models import Account, Order, Position
from .formatting import clean, detail_text, sensitive


class InfoDialog(ModalScreen):
    BINDINGS = [
        Binding("escape,q,enter", "dismiss", "Close"),
        Binding("m,ctrl+h", "app.privacy", "Mask", priority=True),
        Binding("ctrl+c,ctrl+q", "app.quit", show=False, priority=True),
    ]

    def __init__(self, title: str, content):
        super().__init__()
        self.dialog_title, self.content = title, content

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.dialog_title, classes="dialog-title")
            with VerticalScroll():
                yield Static(self.content, markup=False)
            yield Label("Esc close · m mask values", classes="dialog-hint")


class DetailDialog(InfoDialog):
    def __init__(self, row: Position | Order, hidden: bool):
        super().__init__(
            "Position" if isinstance(row, Position) else "Order", detail_text(row, hidden)
        )


class AssetDialog(InfoDialog):
    def __init__(self, asset: Asset, hidden: bool):
        content = Text()
        for label, value in (
            ("Symbol", asset.symbol),
            ("Name", asset.name),
            ("Asset", asset.kind),
            ("Status", asset.state),
            ("Halted", "Yes" if asset.halted else "No"),
            ("Halt regions", asset.regions),
            ("Expiration", asset.expiration),
            ("Strike", asset.strike),
            ("Right", asset.option_type),
            ("Instrument ID", sensitive(asset.identifier, hidden)),
        ):
            if value:
                content.append(f"{label:<17}", style="#8a959e")
                content.append(clean(value) + "\n")
        content.append("\nPublic instrument metadata · display only", style="#7dd3a8")
        super().__init__("Asset details", content)


class AccountDialog(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape,q", "dismiss(None)", "Close"),
        Binding("m,ctrl+h", "app.privacy", "Mask", priority=True),
        Binding("ctrl+c,ctrl+q", "app.quit", show=False, priority=True),
    ]

    def __init__(self, accounts: list[Account], hidden: bool):
        super().__init__()
        self.accounts, self.hidden = accounts, hidden

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Select account · read only", classes="dialog-title")
            yield OptionList(
                *[
                    Text(
                        f"{'MCP' if account.agentic else 'Brokerage'} account {index + 1} · {clean(account.kind)} · "
                        + ("***" if self.hidden else clean(account.number))
                    )
                    for index, account in enumerate(self.accounts)
                ]
            )
            yield Label("↑/↓ select · Enter confirm · Esc close", classes="dialog-hint")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.accounts[event.option_index].number)


class AuthorizationDialog(ModalScreen):
    BINDINGS = [
        Binding("ctrl+y", "copy_url", "Copy URL", priority=True),
        Binding("ctrl+a", "select_url", "Select URL", priority=True),
        Binding("ctrl+t", "show_url", "Show in terminal", priority=True),
        Binding("escape", "dismiss", "Hide"),
        Binding("ctrl+c,ctrl+q", "app.quit", show=False, priority=True),
    ]

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog", classes="authorization"):
            yield Label("Authorize Robinhood", classes="dialog-title")
            yield Static(
                "Open this URL manually in your browser. rhtop never launches one.\n"
                "Return here when authorization completes. The link expires in 10 minutes.",
                markup=False,
            )
            yield TextArea(
                self.url, read_only=True, show_cursor=True, show_line_numbers=False, id="auth-url"
            )
            with Horizontal(id="auth-actions"):
                yield Button("Copy URL", id="copy-auth-url", compact=True)
                yield Button("Show in terminal", id="show-auth-url", compact=True)
            yield Static("", id="auth-copy-note", markup=False)
            yield Label(
                "Ctrl+y copy full URL · Ctrl+t plain terminal · Esc hide · Ctrl+c quit",
                classes="dialog-hint",
            )

    def on_mount(self) -> None:
        self.action_select_url()

    def action_select_url(self) -> None:
        area = self.query_one("#auth-url", TextArea)
        area.focus()
        area.select_all()

    @on(Button.Pressed, "#copy-auth-url")
    def action_copy_url(self) -> None:
        # Copy the original string, never a selection or visually wrapped lines.
        self.app.copy_to_clipboard(self.url)
        self.query_one("#auth-copy-note", Static).update(
            "Copy requested. If pasting fails, use Show in terminal (Ctrl+t)."
        )

    @on(Button.Pressed, "#show-auth-url")
    async def action_show_url(self) -> None:
        try:
            with self.app.suspend():
                print("\nOpen this URL manually to authorize rhtop:\n", flush=True)
                print(self.url, flush=True)
                print(
                    "\nUse your terminal's normal selection/copy controls. "
                    "Press Enter to return to rhtop.",
                    flush=True,
                )
                # Keep the event loop free to receive the OAuth callback while copying.
                try:
                    await asyncio.to_thread(input)
                except EOFError:
                    pass
                except KeyboardInterrupt:
                    self.app.exit(return_code=130)
        except SuspendNotSupported:
            self.query_one("#auth-copy-note", Static).update(
                "Plain terminal is unavailable here. Quit and run rhtop login to print the URL."
            )
