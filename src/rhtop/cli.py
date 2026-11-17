"""Unix entry point. The offline path does not initialize authentication."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from . import __version__
from .auth import TokenVault
from .broker.client import connect
from .broker.dashboard import DashboardReader
from .config import ConnectionConfig
from .demo import DemoReader
from .errors import RhtopError, known_error
from .settings import Settings, config_path, data_path
from .ui.app import RhtopApp


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="rhtop", description="Minimal, read-only Robinhood MCP dashboard. Always headless."
    )
    result.add_argument(
        "command",
        nargs="?",
        default="dashboard",
        choices=("dashboard", "demo", "login", "auth-reset", "paths"),
    )
    result.add_argument(
        "--demo", action="store_true", help="offline sample data; no authentication"
    )
    result.add_argument(
        "--poll-seconds", type=int, metavar="N", help="refresh interval, 10–3600 seconds (saved)"
    )
    result.add_argument(
        "--oauth-port",
        type=int,
        default=8766,
        metavar="PORT",
        help="local callback port (default: 8766)",
    )
    result.add_argument(
        "--headless", action="store_true", help="accepted for clarity; always forced on"
    )
    result.add_argument("--version", action="version", version=f"rhtop {__version__}")
    return result


async def login(config: ConnectionConfig, vault: TokenVault) -> None:
    async with connect(config, vault) as broker:
        accounts = await DashboardReader(broker).accounts()
        eligible = [account for account in accounts if account.agentic]
        if len(eligible) == 1:
            vault.select_account(eligible[0].number)
        print(
            f"Connected. {len(accounts)} account(s), {len(eligible)} MCP / Agentic. Run rhtop to view the dashboard."
        )


def main(argv: list[str] | None = None) -> int:
    args_parser = parser()
    args = args_parser.parse_args(argv)
    if not 1024 <= args.oauth_port <= 65535:
        args_parser.error("--oauth-port must be between 1024 and 65535")
    if args.poll_seconds is not None and not 10 <= args.poll_seconds <= 3600:
        args_parser.error("--poll-seconds must be between 10 and 3600")
    if args.demo and args.command not in ("dashboard", "demo"):
        args_parser.error("--demo applies only to the dashboard")
    # Transport logs can contain URLs or response bodies. rhtop emits safe status only.
    logging.getLogger("mcp").setLevel(logging.CRITICAL)
    logging.getLogger("httpx2").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore2").setLevel(logging.CRITICAL)
    try:
        if args.command == "paths":
            print(f"Preferences: {config_path()}\nEncrypted credentials: {data_path()}")
            return 0
        config = ConnectionConfig(data_path(), args.oauth_port)
        vault = TokenVault(config.data_dir, f"{config.mcp_url}:{config.oauth_port}")
        if args.command == "auth-reset":
            vault.reset()
            print(
                "Local rhtop tokens and saved account removed for this callback port.\n"
                "Robinhood-side authorization is unchanged."
            )
            return 0
        settings = Settings.load(config_path())
        if args.poll_seconds is not None:
            settings.poll_seconds = args.poll_seconds
            settings.save(config_path())
        demo = args.demo or args.command == "demo"
        if args.command != "login" and (not sys.stdin.isatty() or not sys.stdout.isatty()):
            raise RhtopError(
                "The dashboard needs an interactive terminal. Use rhtop --help for commands."
            )
        if not demo:
            vault.unlock()  # Any passphrase prompt happens before Textual takes over.
        if args.command == "login":
            asyncio.run(login(config, vault))
            return 0

        @asynccontextmanager
        async def reader_context(on_authorize):
            if demo:
                yield DemoReader()
            else:
                async with connect(config, vault, on_authorize) as broker:
                    yield DashboardReader(broker)

        app = RhtopApp(reader_context, settings, config_path(), None if demo else vault, demo)
        app.run()
        return app.return_code
    except (KeyboardInterrupt, EOFError):
        return 130
    except Exception as exc:
        error = known_error(exc)
        message = (
            str(error)
            if error
            else "Operation failed. Check permissions, network, or the credential vault."
        )
        print(f"rhtop: {message}", file=sys.stderr)
        return 1
