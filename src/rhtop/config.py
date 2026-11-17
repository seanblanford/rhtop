"""The broker endpoint is fixed; browser launch cannot be enabled."""

from dataclasses import dataclass
from pathlib import Path

MCP_URL = "https://agent.robinhood.com/mcp/trading"


@dataclass(frozen=True)
class ConnectionConfig:
    data_dir: Path
    oauth_port: int = 8766

    @property
    def mcp_url(self) -> str:
        return MCP_URL
