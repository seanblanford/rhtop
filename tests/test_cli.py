import pytest

from rhtop.cli import main


def test_offline_commands_never_unlock_vault(monkeypatch, capsys):
    def forbidden(*args):
        pytest.fail("unexpected authentication")

    monkeypatch.setattr("rhtop.auth.TokenVault.unlock", forbidden)
    assert main(["paths"]) == 0
    with pytest.raises(SystemExit) as version:
        main(["--version"])
    assert version.value.code == 0
    with pytest.raises(SystemExit) as help_result:
        main(["--help"])
    assert help_result.value.code == 0
    assert "rhtop" in capsys.readouterr().out


def test_demo_non_tty_has_helpful_error_without_auth(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("rhtop.auth.TokenVault.unlock", lambda *a: pytest.fail("unexpected auth"))
    assert main(["--demo"]) == 1
    assert "interactive terminal" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args", [["--poll-seconds", "0"], ["--oauth-port", "80"], ["--demo", "login"]]
)
def test_invalid_cli_options(args):
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
