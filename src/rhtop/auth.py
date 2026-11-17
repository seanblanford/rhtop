"""OAuth with a loopback callback and encrypted, per-user credential storage."""

from __future__ import annotations

import asyncio
import base64
import getpass
import hashlib
import json
import os
import secrets
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import keyring
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientInformationFull, OAuthToken

from .errors import RhtopError


def private_write(path: Path, data: bytes) -> None:
    """Write atomically; keep secrets out of intermediate world-readable files."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class TokenVault:
    """SDK TokenStorage backed by Fernet; key in OS keyring or derived from a passphrase."""

    def __init__(self, directory: Path, identity: str, passphrase: str | None = None):
        self.directory = directory
        self.name = hashlib.sha256(identity.encode()).hexdigest()[:24]
        self.path = directory / f"oauth-{self.name}.enc"
        self.meta_path = directory / f"oauth-{self.name}.json"
        self._passphrase = passphrase
        self._cipher: Fernet | None = None

    def _unlock(self) -> Fernet:
        if self._cipher is not None:
            return self._cipher
        try:
            metadata = json.loads(self.meta_path.read_text()) if self.meta_path.exists() else {}
            if not isinstance(metadata, dict):
                raise ValueError
            if self.path.exists() and not metadata:
                raise ValueError
            if metadata and metadata.get("method") not in ("keyring", "passphrase"):
                raise ValueError
        except (ValueError, OSError) as exc:
            raise RhtopError(
                "Cannot read vault metadata; restore it or use rhtop auth-reset"
            ) from exc
        method = metadata.get("method")
        if method in (None, "keyring") and self._passphrase is None:
            try:
                backend = keyring.get_keyring()
                # Never silently select third-party plaintext/null backends.
                backend_module = type(backend).__module__
                if not any(
                    backend_module == module or backend_module.startswith(module + ".")
                    for module in (
                        "keyring.backends.macOS",
                        "keyring.backends.Windows",
                        "keyring.backends.SecretService",
                        "keyring.backends.kwallet",
                    )
                ):
                    raise RhtopError("A secure native keyring is unavailable")
                key = keyring.get_password("rhtop", self.name)
                if key is None:
                    if method == "keyring" and self.path.exists():
                        raise RhtopError(
                            "OAuth encryption key is missing; reconnect with rhtop auth-reset"
                        )
                    key = Fernet.generate_key().decode()
                    keyring.set_password("rhtop", self.name, key)
                self._cipher = Fernet(key.encode())
                private_write(self.meta_path, b'{"method":"keyring"}')
                return self._cipher
            except RhtopError:
                if method == "keyring":
                    raise
            except Exception as exc:
                if method == "keyring":
                    raise RhtopError(
                        "Cannot unlock the OS keyring; unlock it or use rhtop auth-reset"
                    ) from exc
        if method == "keyring":
            raise RhtopError(
                "Existing credentials use the OS keyring; unlock it or use rhtop auth-reset"
            )
        passphrase = self._passphrase or os.environ.get("RHTOP_PASSPHRASE")
        if not passphrase:
            if not sys.stdin.isatty():
                raise RhtopError(
                    "No secure keyring. Run interactively to unlock the encrypted token vault, or provide RHTOP_PASSPHRASE through your secret manager."
                )
            print(
                "No native keyring is available. OAuth tokens will be encrypted with your passphrase."
            )
            passphrase = getpass.getpass("Token vault passphrase (12+ characters): ")
            if not metadata and passphrase != getpass.getpass("Confirm passphrase: "):
                raise RhtopError("Passphrases do not match")
        if len(passphrase) < 12:
            raise RhtopError("Use a token vault passphrase of at least 12 characters")
        salt = base64.b64decode(metadata["salt"]) if metadata else secrets.token_bytes(16)
        key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())
        self._cipher = Fernet(base64.urlsafe_b64encode(key))
        if not metadata:
            private_write(
                self.meta_path,
                json.dumps(
                    {"method": "passphrase", "salt": base64.b64encode(salt).decode()}
                ).encode(),
            )
        return self._cipher

    def _read(self) -> dict:
        cipher = self._unlock()
        if not self.path.exists():
            return {}
        try:
            return json.loads(cipher.decrypt(self.path.read_bytes()))
        except (InvalidToken, ValueError) as exc:
            raise RhtopError(
                "Cannot decrypt OAuth tokens; check your passphrase or use rhtop auth-reset"
            ) from exc

    def _set(self, name: str, value: object) -> None:
        values = self._read()
        values[name] = value
        private_write(self.path, self._unlock().encrypt(json.dumps(values).encode()))

    async def get_tokens(self) -> OAuthToken | None:
        value = self._read().get("tokens")
        return OAuthToken.model_validate(value) if value else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._set("tokens", tokens.model_dump(mode="json"))

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        value = self._read().get("client")
        return OAuthClientInformationFull.model_validate(value) if value else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._set("client", client_info.model_dump(mode="json"))

    def unlock(self) -> None:
        """Prompt before entering the terminal UI, never inside its event loop."""
        self._read()

    def preferred_account(self) -> str | None:
        return self._read().get("preferred_account")

    def select_account(self, number: str) -> None:
        self._set("preferred_account", number)

    def recent_assets(self) -> list[dict]:
        return self._read().get("recent_assets", [])

    def save_recent_assets(self, values: list[dict]) -> None:
        self._set("recent_assets", values)

    def reset(self) -> None:
        self.path.unlink(missing_ok=True)
        self.meta_path.unlink(missing_ok=True)


class OAuthCallback:
    def __init__(self, port: int, on_authorize: Callable[[str], None] | None = None):
        self.port = port
        self.on_authorize = on_authorize
        self.server: asyncio.Server | None = None
        self.future: asyncio.Future | None = None
        self.expected_state: str | None = None

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}/callback"

    async def redirect(self, url: str) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not (
                parsed.hostname == "robinhood.com" or parsed.hostname.endswith(".robinhood.com")
            )
        ):
            raise RhtopError("Refusing an OAuth authorization redirect outside Robinhood")
        self.expected_state = parse_qs(parsed.query).get("state", [None])[0]
        if not self.expected_state:
            raise RhtopError("OAuth request is missing state")
        self.future = asyncio.get_running_loop().create_future()
        try:
            self.server = await asyncio.start_server(
                self._handle, "127.0.0.1", self.port, limit=16384
            )
        except OSError as exc:
            raise RhtopError(
                f"OAuth callback port {self.port} is busy; use --oauth-port to choose another port"
            ) from exc
        if self.on_authorize:
            self.on_authorize(url)
        else:
            print(
                "\nOpen this URL manually to authorize rhtop (no browser will be launched):\n"
                + url
                + "\n"
            )

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        status, message = "400 Bad Request", "Invalid OAuth callback."
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            first = request.decode("ascii").split("\r\n")[0].split(" ")
            parsed = urlsplit(first[1])
            query = parse_qs(parsed.query)
            state = query.get("state", [""])[0]
            if (
                first[0] == "GET"
                and parsed.path == "/callback"
                and self.expected_state
                and secrets.compare_digest(state, self.expected_state)
                and self.future
                and not self.future.done()
            ):
                if query.get("error"):
                    self.future.set_exception(RhtopError("Robinhood authorization was declined"))
                elif query.get("code"):
                    self.future.set_result(
                        AuthorizationCodeResult(
                            code=query["code"][0], state=state, iss=query.get("iss", [None])[0]
                        )
                    )
                    status, message = (
                        "200 OK",
                        "Robinhood connected. You may close this tab and return to the terminal.",
                    )
        except (
            TimeoutError,
            ValueError,
            IndexError,
            UnicodeError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            pass
        finally:
            body = message.encode()
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {len(body)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            try:
                await writer.drain()
            except ConnectionError:
                pass
            writer.close()
            await writer.wait_closed()

    async def receive(self) -> AuthorizationCodeResult:
        try:
            if self.future is None:
                raise RhtopError("OAuth callback was not initialized")
            return await asyncio.wait_for(self.future, 600)
        except TimeoutError as exc:
            raise RhtopError("Robinhood authorization timed out; run again to reconnect") from exc
        finally:
            await self.close()

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
