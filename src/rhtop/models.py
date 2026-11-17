"""Typed, display-only data; no broker payloads are retained or written to disk."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Account:
    number: str = field(repr=False)
    kind: str = "individual"
    crypto_number: str | None = field(default=None, repr=False)
    option_level: int = 0
    agentic: bool = True


@dataclass(frozen=True)
class Position:
    asset: str
    symbol: str
    quantity: Decimal | None = field(repr=False)
    average_price: Decimal | None = field(default=None, repr=False)
    market_value: Decimal | None = field(default=None, repr=False)
    unrealized_pnl: Decimal | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Order:
    asset: str
    symbol: str
    side: str
    state: str
    quantity: Decimal | None = field(repr=False)
    price: Decimal | None = field(repr=False)
    created: str = "—"
    identifier: str = field(default="—", repr=False)


@dataclass(frozen=True)
class Snapshot:
    account: Account
    total_value: Decimal | None = field(repr=False)
    cash: Decimal | None = field(repr=False)
    buying_power: Decimal | None = field(repr=False)
    currency: str = "USD"
    positions: tuple[Position, ...] = ()
    orders: tuple[Order, ...] = ()
    notices: tuple[str, ...] = ()
    updated: datetime | None = None
