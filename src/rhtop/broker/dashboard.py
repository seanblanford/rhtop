"""Account-scoped dashboard reads using only the extracted MCP client."""

from datetime import UTC, datetime

from ..errors import RhtopError, SchemaError
from ..models import Account, Snapshot
from .assets import AssetReader
from .parsing import accounts, decimal, has_more, order, position, scoped_rows, unwrap
from .watchlists import WatchlistReader


class DashboardReader:
    def __init__(self, broker):
        self.broker = broker
        self.assets = AssetReader(broker)
        self.watchlists = WatchlistReader(broker)

    async def accounts(self) -> list[Account]:
        value = await self.broker.call("get_accounts", self.broker.arguments("get_accounts", {}))
        if has_more(value):
            raise SchemaError("Account list is incomplete; cannot safely select an MCP account")
        return accounts(value)

    async def snapshot(self, account: Account) -> Snapshot:
        # Check availability again on every poll; a stale selection is never substituted.
        current = await self.accounts()
        account = next((item for item in current if item.number == account.number), None)
        if account is None:
            raise SchemaError("Selected account is no longer available. Press a to select another.")
        arguments = self.broker.arguments(
            "get_portfolio", {"account_number": account.number}, required_keys=("account_number",)
        )
        portfolio = unwrap(await self.broker.call("get_portfolio", arguments))
        if not isinstance(portfolio, dict):
            raise SchemaError("Unsupported portfolio response")
        if portfolio.get("account_number", account.number) != account.number:
            raise SchemaError("Portfolio returned a different account")
        currency = str(portfolio.get("currency", "USD"))
        if currency != "USD":
            raise SchemaError("Only USD portfolios are supported in this release")
        power = portfolio.get("buying_power")
        power = (
            decimal(power, "buying_power", "unleveraged_buying_power")
            if isinstance(power, dict)
            else decimal(portfolio, "buying_power")
        )
        positions, orders, notices = [], [], []
        for asset in ("equity", "option", "crypto"):
            if asset == "crypto" and not account.crypto_number:
                continue
            for collection, target, parser in (
                ("positions", positions, position),
                ("orders", orders, order),
            ):
                tool = f"get_{asset}_{collection}"
                if tool not in self.broker.schemas:
                    notices.append(f"{asset} {collection}: unavailable")
                    continue
                key = "rhs_account_number" if asset == "crypto" else "account_number"
                values = {key: account.crypto_number if asset == "crypto" else account.number}
                props = self.broker.schemas[tool].get("properties", {})
                scoped = key in props
                try:
                    arguments = self.broker.arguments(
                        tool, values, required_keys=(key,) if scoped else ()
                    )
                    value = await self.broker.call(tool, arguments)
                    rows = scoped_rows(value, collection, account, asset, scoped)
                    parsed = [parser(row, asset) for row in rows]
                    if collection == "positions":
                        parsed = [row for row in parsed if row.quantity != 0]
                    target.extend(parsed)
                    if has_more(value):
                        notices.append(f"{asset} {collection}: partial (first page)")
                except RhtopError:
                    notices.append(f"{asset} {collection}: read failed / unsupported schema")
        return Snapshot(
            account,
            decimal(portfolio, "total_value"),
            decimal(portfolio, "cash"),
            power,
            currency,
            tuple(positions),
            tuple(orders),
            tuple(notices),
            datetime.now(UTC),
        )
