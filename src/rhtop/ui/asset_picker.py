"""A separate display-only browser for catalogs, search results, and recents."""

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, Label, OptionList, Select, Static

from ..assets import Asset, AssetHistory, AssetResults
from .formatting import clean, panel_title


class AssetPicker(Vertical):
    class SearchRequested(Message):
        def __init__(self, kind: str, query: str):
            super().__init__()
            self.kind, self.query = kind, query

    class AssetSelected(Message):
        def __init__(self, asset: Asset):
            super().__init__()
            self.asset = asset

    def __init__(self, history: AssetHistory):
        super().__init__(id="assets", classes="panel")
        self.history = history
        self.kind = "crypto"
        self.results: tuple[Asset, ...] = ()
        self.recent: list[Asset] = []

    def compose(self) -> ComposeResult:
        yield Select(
            [("Crypto", "crypto"), ("Options", "option"), ("Equities", "equity")],
            value="crypto",
            allow_blank=False,
            id="asset-kind",
            compact=True,
        )
        yield Input(
            placeholder="Filter crypto; Enter to reload",
            id="asset-query",
            max_length=120,
            compact=True,
        )
        yield Static("Connecting…", id="asset-status", markup=False)
        yield OptionList(id="asset-results")
        yield Label("RECENT · Enter to reopen", id="recent-label")
        yield OptionList(id="asset-recents")

    def on_mount(self) -> None:
        self.border_title = panel_title(
            4, "Assets", self.app.get_css_variables()["footer-key-foreground"]
        )
        self.update_recents()

    @on(Select.Changed, "#asset-kind")
    def kind_changed(self, event: Select.Changed) -> None:
        event.stop()
        self.kind = str(event.value)
        field = self.query_one("#asset-query", Input)
        field.value = ""
        field.placeholder = (
            "Filter crypto; Enter to reload"
            if self.kind == "crypto"
            else "Company / ticker; Enter to search"
        )
        self.show_results(
            AssetResults(
                (), "Loading…" if self.kind == "crypto" else "Search above or select a recent asset"
            )
        )
        self.update_recents()
        self.post_message(self.SearchRequested(self.kind, ""))

    @on(Input.Submitted, "#asset-query")
    def search_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.show_results(AssetResults((), "Loading…"))
        self.post_message(self.SearchRequested(self.kind, event.value))

    def show_results(self, results: AssetResults) -> None:
        options = self.query_one("#asset-results", OptionList)
        previous = (
            self.results[options.highlighted]
            if options.highlighted is not None and options.highlighted < len(self.results)
            else None
        )
        self.results = results.rows
        options.clear_options()
        options.add_options([Text(clean(asset.title)) for asset in results.rows])
        if results.rows:
            options.highlighted = next(
                (
                    index
                    for index, asset in enumerate(results.rows)
                    if previous
                    and (asset.identifier, asset.symbol) == (previous.identifier, previous.symbol)
                ),
                0,
            )
        self.query_one("#asset-status", Static).update(
            f"{len(results.rows)} results · {results.notice}"
            if results.rows
            else results.notice or "No results"
        )

    def update_recents(self) -> None:
        self.recent = self.history.for_kind(self.kind)
        recent = self.query_one("#asset-recents", OptionList)
        recent.clear_options()
        recent.add_options([Text(clean(asset.title)) for asset in self.recent])
        if self.recent:
            recent.highlighted = 0
        recent.display = self.kind != "crypto" and bool(self.recent)
        self.query_one("#recent-label").display = self.kind != "crypto"

    @on(OptionList.OptionSelected, "#asset-results")
    def select_result(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_index < len(self.results):
            self.post_message(self.AssetSelected(self.results[event.option_index]))

    @on(OptionList.OptionSelected, "#asset-recents")
    def select_recent(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_index < len(self.recent):
            self.post_message(self.AssetSelected(self.recent[event.option_index]))
