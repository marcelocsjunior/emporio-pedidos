#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/vps-common.sh"
REASON=manual
while (($#)); do case $1 in --reason) REASON=${2:-manual}; shift 2;; --dry-run) DRY_RUN=1; shift;; *) die "UNKNOWN_ARGUMENT";; esac; done
[[ $REASON =~ ^[a-zA-Z0-9._-]+$ ]] || die "BACKUP_REASON_INVALID"
APP_IMAGE_TAG=${APP_IMAGE_TAG:-$(sed -n 's/^ACTIVE_SHA=//p' "$RUNTIME_PATH/state/active.env" 2>/dev/null || true)}
require_sha "$APP_IMAGE_TAG"
export APP_IMAGE_TAG
acquire_lock; validate_identity; validate_dependencies; validate_env_file
stamp=$(date +%Y%m%d_%H%M%S)
target="$BACKUP_PATH/postgresql-${stamp}-${REASON}.dump"
meta="$target.meta"
if [[ $DRY_RUN == 1 ]]; then info "DRY_RUN=pg_dump_custom:$target"; exit 0; fi
compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$target"
chmod 600 "$target"
[[ -s $target ]] || die "BACKUP_EMPTY"
compose exec -T db sh -c 'pg_restore --list' <"$target" >/dev/null
digest=$(sha256sum "$target" | awk '{print $1}')
printf 'timestamp=%s\nreason=%s\nfile=%s\nsha256=%s\n' "$(timestamp)" "$REASON" "$(basename "$target")" "$digest" >"$meta"
chmod 600 "$meta"
ln -sfn "$(basename "$target")" "$BACKUP_PATH/latest.dump"
retention=${BACKUP_RETENTION_DAYS:-30}
[[ $retention =~ ^[0-9]+$ ]] || die "RETENTION_INVALID"
previous_backup=$(sed -n 's/^PREVIOUS_BACKUP=//p' "$RUNTIME_PATH/state/active.env" 2>/dev/null || true)
find "$BACKUP_PATH" -maxdepth 1 -type f -name 'postgresql-*.dump' -mtime "+$retention" ! -name "$(basename "$target")" ! -name "$(basename "${previous_backup:-protected-none}")" -delete
info "BACKUP=SUCCESS"; info "BACKUP_SHA256=$digest"
