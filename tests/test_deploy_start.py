import subprocess

import pytest

from scripts import deploy_start
from scripts.deploy_start import (
    DeploymentError,
    _configure_sparse_checkout,
    _enabled,
    _load_deployment_environment,
    _prepare_repository,
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


def test_uploaded_release_bootstraps_when_auto_update_has_no_git_data(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(deploy_start, "ROOT", tmp_path)
    monkeypatch.setattr(deploy_start, "RUNTIME_DIRECTORY", tmp_path / "runtime")
    monkeypatch.setenv("AUTO_UPDATE", "1")
    monkeypatch.setenv("DEPLOY_GIT_REMOTE", "aestron")
    monkeypatch.setenv("DEPLOY_GIT_BRANCH", "master")
    monkeypatch.setenv(
        "DEPLOY_GIT_REMOTE_URL", "https://github.com/example/aestron.git"
    )
    commands = []

    def fake_run(command, *, label, check=True):
        commands.append(command)
        bootstrap_directory = tmp_path / "runtime" / "git-bootstrap"
        (bootstrap_directory / ".git").mkdir(parents=True)
        return subprocess.CompletedProcess(command, 0, "", "")

    def fake_git(*arguments, label="Git command"):
        if arguments[:2] == ("remote", "get-url"):
            return "https://github.com/example/aestron.git"
        if arguments[:2] == ("rev-parse", "aestron/master"):
            return "abc123"
        if arguments[:1] == ("describe",):
            return "v1.2.3"
        return ""

    monkeypatch.setattr(deploy_start, "_run", fake_run)
    monkeypatch.setattr(deploy_start, "_git", fake_git)

    repository_info = _prepare_repository("website")

    assert repository_info == ("abc123", "master", "v1.2.3", True)
    assert (tmp_path / ".git").is_dir()
    assert commands[0][:5] == [
        "git",
        "clone",
        "--quiet",
        "--no-checkout",
        "--filter=blob:none",
    ]
    assert "creating a checkout" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("service", "included", "excluded"),
    [
        ("website", "/website/", "/aestron_bot/"),
        ("bot", "/aestron_bot/", "/website/"),
    ],
)
def test_sparse_checkout_contains_only_service_files(
    monkeypatch, tmp_path, service, included, excluded
):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(deploy_start, "ROOT", tmp_path)
    calls = []

    def fake_git(*arguments, label="Git command"):
        calls.append(arguments)
        return ""

    monkeypatch.setattr(deploy_start, "_git", fake_git)

    _configure_sparse_checkout(service)

    sparse_set = calls[1]
    assert sparse_set[:3] == ("sparse-checkout", "set", "--no-cone")
    assert included in sparse_set
    assert excluded not in sparse_set
    assert (tmp_path / ".git" / "aestron-service").read_text().strip() == service
