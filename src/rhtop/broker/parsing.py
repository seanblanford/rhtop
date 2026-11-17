"""Supported MCP envelopes; missing numbers stay unknown."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ..errors import SchemaError
from ..models import Account, Order, Position


def unwrap(value: Any) -> Any:
    for _ in range(4):
        if isinstance(value, dict) and "data" in value:
            value = value["data"]
        elif isinstance(value, dict) and set(value) == {"result"}:
            value = value["result"]
        else:
            return value
    raise SchemaError("Broker response has unsupported nesting")


def records(value: Any, *keys: str) -> list[dict]:
    value = unwrap(value)
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    if isinstance(value, dict):
        for name in (*keys, "results"):
            if name not in value:
                continue
            rows = value[name]
            if rows is None:
                return []
            if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
                return rows
            if isinstance(rows, dict):
                return (
                    list(rows.values())
                    if all(isinstance(v, dict) for v in rows.values())
                    else [rows]
                )
    raise SchemaError("Broker returned an unsupported record collection")


def decimal(row: dict, *names: str) -> Decimal | None:
    for name in names:
        value = row.get(name)
        if value is not None:
            try:
                result = Decimal(str(value))
                if not result.is_finite():
                    raise ValueError
                return result
            except (InvalidOperation, ValueError) as exc:
                raise SchemaError("Broker returned an invalid financial value") from exc
    return None


def accounts(value: Any) -> list[Account]:
    result = []
    for row in records(value, "accounts"):
        if row.get("state", row.get("status", "active")) not in ("active", "open", "approved"):
            continue
        if any(
            row.get(key) is True
            for key in ("is_closed", "is_deactivated", "deactivated", "permanently_deactivated")
        ):
            continue
        number = row.get("account_number")
        if not isinstance(number, str) or not number:
            raise SchemaError("MCP account identifier is missing")
        level = str(row.get("option_level", "0")).removeprefix("option_level_")
        crypto = (
            bool(row.get("rhc_account_number"))
            if "rhc_account_number" in row or "brokerage_account_type" in row
            else bool(row.get("rhs_account_number"))
        )
        result.append(
            Account(
                number,
                str(row.get("brokerage_account_type", "individual")),
                row.get("rhs_account_number") if crypto else None,
                int(level) if level.isdigit() else 0,
                row.get("agentic_allowed") is True,
            )
        )
    if len({account.number for account in result}) != len(result):
        raise SchemaError("Duplicate MCP accounts returned")
    if not result:
        raise SchemaError("No active brokerage accounts were returned by the MCP connection")
    return result


def has_more(value: Any) -> bool:
    return any(
        isinstance(row, dict)
        and any(row.get(key) for key in ("next", "next_cursor", "next_page_token", "has_more"))
        for row in (value, unwrap(value))
    )


def scoped_rows(value: Any, key: str, account: Account, asset: str, scoped: bool) -> list[dict]:
    rows = records(value, key)
    scope_key = "rhs_account_number" if asset == "crypto" else "account_number"
    expected = account.crypto_number if asset == "crypto" else account.number
    result = []
    for row in rows:
        actual = row.get(scope_key)
        if actual is not None:
            if actual != expected:
                continue
        elif not scoped:
            raise SchemaError(f"Unscoped {asset} {key}; no account identifier")
        result.append(row)
    return result


def symbol(row: dict) -> str:
    value = row.get("symbol") or row.get("chain_symbol")
    if not value and isinstance(row.get("currency"), dict):
        value = row["currency"].get("code")
    # Never expose a contract UUID in the public symbol column.
    return str(value) if value else "Unknown"


def position(row: dict, asset: str) -> Position:
    return Position(
        asset,
        symbol(row),
        decimal(row, "quantity"),
        decimal(row, "average_buy_price", "average_price"),
        decimal(row, "market_value", "equity", "value"),
        decimal(row, "unrealized_pnl", "unrealized_gain_loss"),
    )


def order(row: dict, asset: str) -> Order:
    return Order(
        asset,
        symbol(row),
        str(row.get("side", "—")),
        str(row.get("state", row.get("status", "—"))),
        decimal(row, "quantity", "total_quantity"),
        decimal(row, "limit_price", "price", "average_price"),
        str(row.get("created_at", "—")),
        str(row.get("id", row.get("order_id", "—"))),
    )
