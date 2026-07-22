from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "deploy/docker-compose.vps.yml"
SCRIPTS = sorted((ROOT / "ops").glob("vps-*.sh"))
PILOT_IDENTIFIERS = (
    "emporio-pedidos-teste",
    "emporio_pedidos_vps_teste_emporio_pgdata",
)


def read(path: str | Path) -> str:
    return (ROOT / path).read_text() if isinstance(path, str) else path.read_text()


def test_required_files_and_executable_scripts():
    required = [
        ".dockerignore",
        "deploy/docker-compose.vps.yml",
        "deploy/env.vps.example",
        "docs/DEPLOY_VPS_8850.md",
        *[str(path.relative_to(ROOT)) for path in SCRIPTS],
    ]
    assert all((ROOT / path).is_file() for path in required)
    assert len(SCRIPTS) == 6
    for script in SCRIPTS:
        assert script.stat().st_mode & stat.S_IXUSR
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_compose_services_isolation_and_healthchecks():
    text = read(COMPOSE_PATH)
    for service in ["db", "web", "worker"]:
        assert re.search(rf"^  {service}:$", text, re.MULTILINE)
    db_block = text.split("  db:", 1)[1].split("\n  web:", 1)[0]
    web_block = text.split("  web:", 1)[1].split("\n  worker:", 1)[0]
    worker_block = text.split("  worker:", 1)[1].split("\nvolumes:", 1)[0]
    assert "ports:" not in db_block
    assert "healthcheck:" in db_block and "healthcheck:" in web_block
    assert "restart: unless-stopped" in text
    assert "${DB_VOLUME_NAME:-emporio_pedidos_producao_pgdata}" in text
    assert "${APP_PORT:-8850}:8000" in text
    assert "migrate" not in web_block
    assert '["python", "manage.py", "run_ai_worker", "--interval", "900"]' in worker_block
    assert "<<: *app" in web_block and "<<: *app" in worker_block
    assert text.count("env_file:") >= 2
    assert not any(marker in text for marker in PILOT_IDENTIFIERS)
    assert "8020" not in text


def test_dockerignore_excludes_sensitive_runtime_content():
    ignored = read(".dockerignore")
    patterns = [
        ".git",
        ".env",
        "*.sqlite3",
        "*.dump",
        "backups/",
        "logs/",
        "media/",
        "staticfiles/",
        "*.key",
    ]
    for pattern in patterns:
        assert pattern in ignored


def test_image_revision_is_oci_labeled():
    dockerfile = read("Dockerfile")
    assert "ARG APP_REVISION" in dockerfile
    assert 'org.opencontainers.image.revision="${APP_REVISION}"' in dockerfile


def test_pilot_protection_fails_closed_and_sha_is_mandatory():
    common = read("ops/vps-common.sh")
    deploy = read("ops/vps-deploy.sh")
    for marker in ["8020", "emporio_pedidos_vps_teste", "/opt/emporio-pedidos-teste"]:
        assert marker in common
    assert "PILOT_PROTECTION=ENABLED" in common
    assert 'require_sha "$REQUESTED_SHA"' in deploy
    assert "DEPLOY_MODE=NO_OP" in deploy and "mode=RECONCILE" in deploy
    assert "--dry-run" in deploy and "--preflight-only" in deploy


def test_backup_and_rollback_safety_contracts():
    backup = read("ops/vps-backup.sh")
    rollback = read("ops/vps-rollback.sh")
    deploy = read("ops/vps-deploy.sh")
    assert "pg_dump" in backup and "-Fc" in backup
    assert "pg_restore --list" in backup and "sha256sum" in backup
    assert "DATABASE_RESTORE=NEVER_AUTOMATIC" in rollback
    assert not re.search(r"pg_restore\s+.*(-d|--dbname)", rollback)
    assert "createsuperuser" not in deploy
    assert "bootstrap_roles" in deploy


def test_environment_template_has_no_real_secrets():
    env = read("deploy/env.vps.example")
    assert "APP_PORT=8850" in env
    assert "AI_ENABLED=0" in env
    assert not re.search(r"(?i)(password|secret)=((?!generate-|set-by-).)+", env)


def test_scripts_do_not_log_environment_contents_or_password_arguments():
    combined = "\n".join(read(path) for path in SCRIPTS)
    assert "cat $ENV_FILE" not in combined and 'cat "$ENV_FILE"' not in combined
    assert "--password" not in combined
    assert "sanitize" in read("ops/vps-common.sh")
    assert os.path.basename(SCRIPTS[0])
