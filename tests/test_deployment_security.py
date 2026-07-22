from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "ops/vps-common.sh"


def bash(script: str, *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def settings(cookie_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": "test-only"})
    env.pop("DJANGO_SESSION_COOKIE_SECURE", None)
    env.pop("DJANGO_CSRF_COOKIE_SECURE", None)
    env.update(cookie_env or {})
    return subprocess.run(
        [
            "python",
            "-c",
            "from config.settings import *; print(SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE)",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_run_discards_label_and_preserves_arguments():
    result = bash(f'source "{COMMON}"; run label printf "%s|%s" "hello world" tail')
    assert result.returncode == 0
    assert result.stdout == "hello world|tail"


def test_run_propagates_command_failure_and_dry_run_does_not_execute():
    failed = bash(f'source "{COMMON}"; run ignored bash -c "exit 37"')
    assert failed.returncode == 37
    dry = bash(f'source "{COMMON}"; DRY_RUN=1; run label touch /tmp/must-not-exist-pr21')
    assert dry.returncode == 0
    assert "DRY_RUN_LABEL=label" in dry.stdout
    assert not Path("/tmp/must-not-exist-pr21").exists()


def test_host_validation_requires_exact_real_hostname(tmp_path: Path):
    env_file = tmp_path / "env"
    env_file.write_text("DEPLOY_HOST_ID=definitely-not-this-host\n")
    mismatch = bash(f'source "{COMMON}"; ENV_FILE="{env_file}"; validate_host')
    assert mismatch.returncode != 0 and "HOST_ID_MISMATCH" in mismatch.stderr
    env_file.write_text("")
    missing = bash(f'source "{COMMON}"; ENV_FILE="{env_file}"; validate_host')
    assert missing.returncode != 0 and "ENV_KEY_INVALID" in missing.stderr


def test_secret_validation_rejects_placeholders_and_weak_values(tmp_path: Path):
    env_file = tmp_path / "env"
    env_file.write_text(
        "DJANGO_SECRET_KEY=generate-a-new-random-secret\n"
        "POSTGRES_PASSWORD=generate-a-new-random-password\n"
    )
    placeholder = bash(f'source "{COMMON}"; ENV_FILE="{env_file}"; validate_secrets')
    assert placeholder.returncode != 0
    env_file.write_text("DJANGO_SECRET_KEY=short\nPOSTGRES_PASSWORD=also-short\n")
    weak = bash(f'source "{COMMON}"; ENV_FILE="{env_file}"; validate_secrets')
    assert weak.returncode != 0


def test_worktree_validation_rejects_tracked_and_untracked_changes(tmp_path: Path):
    if shutil.which("git") is None:
        import pytest

        pytest.skip("git is supplied by CI runner; minimal runtime image omits it")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "ci@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "CI"], check=True)
    tracked = tmp_path / "tracked"
    tracked.write_text("clean")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "initial"], check=True)
    clean = bash(f'source "{COMMON}"; APP_PATH="{tmp_path}"; validate_worktree')
    assert clean.returncode == 0 and "GIT_WORKTREE_CLEAN=SIM" in clean.stdout
    (tmp_path / "untracked").write_text("dirty")
    dirty = bash(f'source "{COMMON}"; APP_PATH="{tmp_path}"; validate_worktree')
    assert dirty.returncode != 0 and "GIT_WORKTREE_DIRTY" in dirty.stderr


def test_cookie_security_default_http_and_invalid_value():
    secure = settings()
    assert secure.returncode == 0 and secure.stdout.strip() == "True True"
    http = settings({"DJANGO_SESSION_COOKIE_SECURE": "0", "DJANGO_CSRF_COOKIE_SECURE": "0"})
    assert http.returncode == 0 and http.stdout.strip() == "False False"
    invalid = settings({"DJANGO_SESSION_COOKIE_SECURE": "false"})
    assert invalid.returncode != 0


def test_security_middleware_and_template_contract():
    settings_text = (ROOT / "config/settings.py").read_text()
    env_text = (ROOT / "deploy/env.vps.example").read_text()
    assert "django.middleware.csrf.CsrfViewMiddleware" in settings_text
    assert "django.contrib.sessions.middleware.SessionMiddleware" in settings_text
    assert "DJANGO_SESSION_COOKIE_SECURE=0" in env_text
    assert "DJANGO_CSRF_COOKIE_SECURE=0" in env_text
    assert "DJANGO_ALLOWED_HOSTS=*" not in env_text


def test_automatic_rollback_contract_and_no_database_restore():
    deploy = (ROOT / "ops/vps-deploy.sh").read_text()
    rollback = (ROOT / "ops/vps-rollback.sh").read_text()
    assert "trap 'deploy_failure $?' ERR" in deploy
    assert "AUTO_ROLLBACK=SUCCESS" in deploy
    assert "DB_ROLLBACK_DECISION_REQUIRED=SIM" in deploy
    assert "pg_restore" not in deploy and "pg_restore" not in rollback
