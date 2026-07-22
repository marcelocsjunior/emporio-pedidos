#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/vps-common.sh"
validate_identity
state_file="$RUNTIME_PATH/state/active.env"
if [[ ! -f $state_file ]]; then info "STATUS=UNAVAILABLE"; exit 2; fi
APP_IMAGE_TAG=$(sed -n 's/^ACTIVE_SHA=//p' "$state_file"); export APP_IMAGE_TAG
require_sha "$APP_IMAGE_TAG"
printf 'ACTIVE_SHA=%s\nIMAGE=%s\nPORT=8850\nVOLUME=%s\n' "$APP_IMAGE_TAG" "$(sed -n 's/^IMAGE=//p' "$state_file")" "$EXPECTED_VOLUME"
compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Health}}' 2>/dev/null || { info "STATUS=UNAVAILABLE"; exit 2; }
printf 'DB_RESTARTS=%s\nWEB_RESTARTS=%s\nWORKER_RESTARTS=%s\n' "$(container_restart_count db)" "$(container_restart_count web)" "$(container_restart_count worker)"
pending=$(compose run --rm web python manage.py showmigrations --plan 2>/dev/null | grep -c '^\[ \]' || true)
printf 'MIGRATIONS_PENDING=%s\nLAST_BACKUP=%s\nLAST_DEPLOYMENT=%s\n' "$pending" "$(readlink "$BACKUP_PATH/latest.dump" 2>/dev/null || echo none)" "$(tail -n1 "$RUNTIME_PATH/deployments.log" 2>/dev/null | sanitize)"
if [[ $pending == 0 ]] && [[ $(compose ps --status running --services | wc -l) -eq 3 ]]; then info "STATUS=HEALTHY"; else info "STATUS=DEGRADED"; exit 1; fi
