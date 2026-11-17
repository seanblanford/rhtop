"""Public asset metadata and private, bounded recent selections."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .auth import TokenVault, private_write
from .errors import RhtopError

ASSET_KINDS = ("crypto", "option", "equity")


@dataclass(frozen=True)
class Asset:
    kind: str
    symbol: str
    name: str = ""
    identifier: str = ""
    state: str = ""
    halted: bool = False
    regions: str = ""
    expiration: str = ""
    strike: str = ""
    option_type: str = ""
    underlying: bool = False

    @property
    def title(self) -> str:
        if self.kind == "option" and not self.underlying:
            title = f"{self.symbol} {self.expiration} {self.strike} {self.option_type}"
        else:
            title = f"{self.symbol} · {self.name}" if self.name else self.symbol
        regions = " ".join(self.regions.replace(",", " ").split())
        suffix = (" 🚫" + (f" {regions}" if regions else "")) if self.halted else ""
        return title[: min(140, max(0, 160 - len(suffix)))] + suffix


@dataclass(frozen=True)
class AssetResults:
    rows: tuple[Asset, ...]
    notice: str = ""


class AssetHistory:
    """Live selections share the encrypted vault; demo selections use a private file."""

    LIMIT = 30

    def __init__(self, vault: TokenVault | None, demo_path: Path):
        self.vault, self.demo_path = vault, demo_path
        try:
            values = (
                vault.recent_assets()
                if vault
                else json.loads(demo_path.read_text())
                if demo_path.exists()
                else []
            )
            if not isinstance(values, list):
                raise ValueError
            self.items = [Asset(**value) for value in values[: self.LIMIT * 2]]
            if any(
                item.kind not in ("equity", "option")
                or item.underlying
                or any(
                    not isinstance(value, str) or len(value) > 256
                    for key, value in asdict(item).items()
                    if key not in ("halted", "underlying")
                )
                for item in self.items
            ):
                raise ValueError
        except (TypeError, ValueError, OSError) as exc:
            raise RhtopError(
                "Cannot load asset recents. Restore the vault or remove demo-recents.json."
            ) from exc

    def for_kind(self, kind: str) -> list[Asset]:
        return [item for item in self.items if item.kind == kind]

    def remember(self, asset: Asset) -> None:
        if asset.kind not in ("equity", "option") or asset.underlying:
            return
        items = [asset] + [
            item
            for item in self.items
            if (item.kind, item.identifier, item.symbol)
            != (asset.kind, asset.identifier, asset.symbol)
        ]
        self.items = [
            item
            for kind in ("equity", "option")
            for item in [row for row in items if row.kind == kind][: self.LIMIT]
        ]
        values = [asdict(item) for item in self.items]
        if self.vault:
            self.vault.save_recent_assets(values)
        else:
            private_write(self.demo_path, (json.dumps(values) + "\n").encode())
