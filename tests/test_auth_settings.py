import asyncio
import json
import os
from pathlib import Path

import pytest
from mcp.shared.auth import OAuthToken

from rhtop.auth import OAuthCallback, TokenVault
from rhtop.errors import RhtopError
from rhtop.settings import Settings


async def test_vault_encrypts_credentials_and_selection(tmp_path):
    secret = "synthetic-access-token"
    vault = TokenVault(tmp_path, "synthetic", "a sufficiently long passphrase")
    await vault.set_tokens(OAuthToken(access_token=secret, refresh_token="synthetic-refresh"))
    vault.select_account("PRIVATE12345")
    stored = vault.path.read_bytes()
    assert secret.encode() not in stored and b"PRIVATE12345" not in stored
    reopened = TokenVault(tmp_path, "synthetic", "a sufficiently long passphrase")
    assert (await reopened.get_tokens()).access_token == secret
    assert reopened.preferred_account() == "PRIVATE12345"
    wrong = TokenVault(tmp_path, "synthetic", "another sufficiently long passphrase")
    with pytest.raises(RhtopError, match="decrypt"):
        await wrong.get_tokens()
    if os.name == "posix":
        assert vault.path.stat().st_mode & 0o777 == 0o600
        assert vault.meta_path.stat().st_mode & 0o777 == 0o600


def test_settings_private_atomic_roundtrip(tmp_path):
    path = tmp_path / "new" / "settings.json"
    settings = Settings(layout="mirrored", panels=["account", "orders"])
    settings.save(path)
    assert Settings.load(path) == settings
    assert set(json.loads(path.read_text())) == {
        "poll_seconds",
        "layout",
        "panels",
        "sort_descending",
    }
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
    assert len(list(path.parent.iterdir())) == 1


@pytest.mark.parametrize(
    "data",
    [
        "invalid",
        "[]",
        '{"poll_seconds": 0}',
        '{"panels": []}',
        '{"panels": ["orders", "orders"]}',
        '{"layout": "bad"}',
    ],
)
def test_bad_settings_are_not_silently_overwritten(tmp_path, data):
    path = tmp_path / "settings.json"
    path.write_text(data)
    with pytest.raises(RhtopError):
        Settings.load(path)
    assert path.read_text() == data


async def test_loopback_callback_requires_state_and_never_opens_browser(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("browser launch is forbidden")

    monkeypatch.setattr("webbrowser.open", forbidden)
    urls = []
    callback = OAuthCallback(0, urls.append)
    await callback.redirect("https://robinhood.com/authorize?state=synthetic-state")
    port = callback.server.sockets[0].getsockname()[1]

    async def request(state):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(
            f"GET /callback?code=synthetic-code&state={state} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
        )
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        return response

    try:
        assert b"400 Bad Request" in await request("wrong-state")
        assert not callback.future.done()
        assert b"200 OK" in await request("synthetic-state")
        assert (await callback.receive()).code == "synthetic-code"
        assert len(urls) == 1
    finally:
        await callback.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/?state=x",
        "http://robinhood.com/?state=x",
        "https://robinhood.com.evil.test/?state=x",
        "https://robinhood.com/",
    ],
)
async def test_callback_rejects_bad_authorization_urls(url):
    with pytest.raises(RhtopError):
        await OAuthCallback(0).redirect(url)


def test_no_browser_launch_api_exists():
    source = Path("src/rhtop/auth.py").read_text()
    assert "webbrowser" not in source
    assert "open_browser" not in source


def test_missing_vault_metadata_is_never_regenerated_over_existing_ciphertext(tmp_path):
    vault = TokenVault(tmp_path, "test", "a long synthetic passphrase")
    vault.select_account("SYNTHETIC")
    original = vault.path.read_bytes()
    vault.meta_path.unlink()
    reopened = TokenVault(tmp_path, "test", "a long synthetic passphrase")
    with pytest.raises(RhtopError, match="metadata"):
        reopened.unlock()
    assert reopened.path.read_bytes() == original
    assert not reopened.meta_path.exists()
