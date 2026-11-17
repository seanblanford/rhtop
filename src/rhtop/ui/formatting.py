"""One privacy boundary for account, table, and detail views."""

from decimal import Decimal

from rich.style import Style
from rich.text import Text

from ..models import Order, Position, Snapshot

MASK = "***"


def panel_title(key: int, label: str, key_color: str) -> Text:
    """Match the footer shortcut color without recoloring the panel label."""
    return Text.assemble((str(key), f"bold {key_color}"), f" {label}")


def clean(value: object) -> str:
    """Broker strings are plain text, never terminal controls or Rich markup."""
    return "".join(c for c in str(value) if c.isprintable())[:160]


def sensitive(value: object, hidden: bool, *, money: bool = False) -> str:
    if hidden:
        return MASK
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        return f"${value:,.2f}" if money else f"{value:,.8f}".rstrip("0").rstrip(".")
    return clean(value)


def position_cells(row: Position, hidden: bool) -> tuple[str, ...]:
    return (
        clean(row.symbol),
        clean(row.asset),
        sensitive(row.quantity, hidden),
        sensitive(row.average_price, hidden, money=True),
        sensitive(row.market_value, hidden, money=True),
        sensitive(row.unrealized_pnl, hidden, money=True),
    )


def order_cells(row: Order, hidden: bool) -> tuple[str, ...]:
    return (
        clean(row.symbol),
        clean(row.asset),
        clean(row.side),
        clean(row.state),
        sensitive(row.quantity, hidden),
        sensitive(row.price, hidden, money=True),
        clean(row.created).replace("T", " ").removesuffix("Z")[:16],
    )


def account_text(snapshot: Snapshot | None, hidden: bool, demo: bool) -> Text:
    text = Text()
    title_text = (
        "MCP /agentic\n\n" if snapshot is None or snapshot.account.agentic else "Brokerage\n\n"
    )
    text.append(title_text, style="bold #7dd3a8")
    if snapshot is None:
        text.append("Loading accounts…", style="#8a959e")
        return text
    text.append("ACCOUNT", style=Style(color="#8a959e", meta={"@click": "app.accounts"}))
    text.append(" MCP" if snapshot.account.agentic else "", style="#7dd3a8")
    account_kind = " " + clean(snapshot.account.kind).replace("_", " ") + "\n"
    text.append(account_kind, style="#8a959e")
    text.append(
        sensitive(snapshot.account.number, hidden),
        style=Style(color="#7dd3a8", bold=True, meta={"@click": "app.copy_account_id"}),
    )
    text.append("\n\n")
    for label, value in (
        ("Portfolio", snapshot.total_value),
        ("Cash", snapshot.cash),
        ("Buying power", snapshot.buying_power),
    ):
        text.append(label + "\n", style="#8a959e")
        text.append(sensitive(value, hidden, money=True) + "\n\n", style="bold")
    if demo:
        text.append("OFFLINE DEMO\nSample values", style="#e9bd73")
    return text


def detail_text(row: Position | Order, hidden: bool) -> Text:
    if isinstance(row, Position):
        labels = ("Symbol", "Asset", "Quantity", "Average price", "Market value", "Unrealized P/L")
        values = position_cells(row, hidden)
    else:
        labels = ("Symbol", "Asset", "Side", "State", "Quantity", "Price", "Created", "Order ID")
        values = (*order_cells(row, hidden), sensitive(row.identifier, hidden))
    text = Text()
    for label, value in zip(labels, values, strict=True):
        text.append(f"{label:<17}", style="#8a959e")
        text.append(value + "\n")
    return text
