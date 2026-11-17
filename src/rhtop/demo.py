"""Deterministic, offline sample data. Never connects or touches the credential vault."""

from datetime import UTC, datetime
from decimal import Decimal as D

from .assets import Asset, AssetResults
from .broker.watchlists import Watchlist
from .models import Account, Order, Position, Snapshot


class DemoReader:
    @property
    def watchlists(self):
        return self

    async def lists(self):
        return (
            Watchlist("demo-stocks", "My Watchlist"),
            Watchlist("demo-crypto", "Crypto", "robinhood"),
        )

    async def items(self, watchlist):
        if watchlist.identifier == "demo-crypto":
            return ("BTC-USD · currency_pair", "ETH-USD · currency_pair")
        return ("AAPL · instrument", "NVDA · instrument", "SPX · index")

    @property
    def assets(self):
        return self

    async def browse(self, kind: str, query: str = "", *, underlying: bool = False) -> AssetResults:
        if kind == "crypto":
            rows = (
                Asset("crypto", "BTC-USD", "Bitcoin", "demo-btc", "tradable"),
                Asset("crypto", "ETH-USD", "Ethereum", "demo-eth", "tradable"),
                Asset("crypto", "SOL-USD", "Solana", "demo-sol", "tradable"),
                Asset(
                    "crypto", "DEMO-USD", "Demo halted coin", "demo-halt", "limited", True, "ALL"
                ),
            )
            return AssetResults(
                tuple(row for row in rows if query.casefold() in row.title.casefold()),
                "Offline sample catalog",
            )
        if not query:
            return AssetResults((), "Search a company or ticker; select a result to save")
        symbol = "AAPL" if "apple" in query.casefold() else query.split()[0].upper()
        if kind == "option" and underlying:
            return AssetResults(
                tuple(
                    Asset(
                        "option",
                        symbol,
                        identifier=f"demo-{symbol}-{right}",
                        state="active / tradable",
                        expiration="2026-12-18",
                        strike="250",
                        option_type=right,
                    )
                    for right in ("call", "put")
                ),
                "Offline sample contracts",
            )
        return AssetResults(
            (
                Asset(
                    kind,
                    symbol,
                    "Apple" if symbol == "AAPL" else "Demo asset",
                    f"demo-{symbol}",
                    underlying=kind == "option",
                ),
            )
        )

    async def accounts(self) -> list[Account]:
        return [Account("DEMO0001", "individual", "DEMOCRYPTO", 2)]

    async def snapshot(self, account: Account) -> Snapshot:
        return Snapshot(
            account,
            D("24835.62"),
            D("6842.20"),
            D("6842.20"),
            "USD",
            (
                Position("equity", "AAPL", D("12"), D("182.40"), D("2736.48"), D("547.68")),
                Position("equity", "VOO", D("18.5"), D("480.25"), D("10342.44"), D("1457.81")),
                Position("equity", "NVDA", D("20"), D("119.80"), D("2961.20"), D("565.20")),
                Position("crypto", "BTC", D("0.0185"), D("82000"), D("1953.30"), D("436.30")),
            ),
            (
                Order(
                    "equity",
                    "AAPL",
                    "buy",
                    "queued",
                    D("2"),
                    D("220"),
                    "2026-11-15T13:20:00Z",
                    "demo-order-01",
                ),
                Order(
                    "equity",
                    "VOO",
                    "buy",
                    "filled",
                    D("0.5"),
                    D("559.05"),
                    "2026-11-14T15:32:00Z",
                    "demo-order-02",
                ),
                Order(
                    "crypto",
                    "BTC",
                    "buy",
                    "confirmed",
                    D("0.001"),
                    D("102000"),
                    "2026-11-14T12:10:00Z",
                    "demo-order-03",
                ),
            ),
            (),
            datetime.now(UTC),
        )
