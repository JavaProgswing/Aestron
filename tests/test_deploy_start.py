import pytest

from scripts import deploy_start
from scripts.deploy_start import (
    DeploymentError,
    _enabled,
    _load_deployment_environment,
    _validate_remote_url,
)


def test_deployment_remote_accepts_secure_credential_free_urls():
    _validate_remote_url("https://github.com/example/aestron.git")
    _validate_remote_url("git@github.com:example/aestron.git")
    _validate_remote_url("ssh://git@github.com/example/aestron.git")


@pytest.mark.parametrize(
    "remote_url",
    [
        "http://github.com/example/aestron.git",
        "https://token@github.com/example/aestron.git",
        "https://user:token@github.com/example/aestron.git",
        "file:///tmp/aestron",
    ],
)
def test_deployment_remote_rejects_insecure_or_embedded_credentials(remote_url):
    with pytest.raises(DeploymentError):
        _validate_remote_url(remote_url)


def test_deployment_boolean_is_strict(monkeypatch):
    monkeypatch.setenv("AUTO_UPDATE", "sometimes")
    with pytest.raises(DeploymentError, match="AUTO_UPDATE"):
        _enabled("AUTO_UPDATE", True)


def test_github_env_loads_only_allowlisted_deployment_settings(monkeypatch, tmp_path):
    (tmp_path / "github.env").write_text(
        "AUTO_UPDATE=1\n"
        "DEPLOY_GIT_REMOTE=aestron\n"
        "GITHUB_TOKEN=must-not-enter-process-environment\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(deploy_start, "ROOT", tmp_path)
    monkeypatch.delenv("AUTO_UPDATE", raising=False)
    monkeypatch.delenv("DEPLOY_GIT_REMOTE", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    _load_deployment_environment()

    assert deploy_start.os.environ["AUTO_UPDATE"] == "1"
    assert deploy_start.os.environ["DEPLOY_GIT_REMOTE"] == "aestron"
    assert "GITHUB_TOKEN" not in deploy_start.os.environ


def test_pterodactyl_variables_override_github_env(monkeypatch, tmp_path):
    (tmp_path / "github.env").write_text(
        "DEPLOY_GIT_REMOTE=aestron\n", encoding="utf-8"
    )
    monkeypatch.setattr(deploy_start, "ROOT", tmp_path)
    monkeypatch.setenv("DEPLOY_GIT_REMOTE", "origin")

    _load_deployment_environment()

    assert deploy_start.os.environ["DEPLOY_GIT_REMOTE"] == "origin"
