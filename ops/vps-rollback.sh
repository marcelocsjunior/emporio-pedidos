#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/vps-common.sh"
TARGET_SHA=; PREVIOUS=0
while (($#)); do case $1 in --to-sha) TARGET_SHA=${2:-}; shift 2;; --previous) PREVIOUS=1; shift;; --dry-run) DRY_RUN=1; shift;; *) die "UNKNOWN_ARGUMENT";; esac; done
state_file="$RUNTIME_PATH/state/active.env"
[[ -f $state_file ]] || die "DEPLOYMENT_STATE_MISSING"
[[ $PREVIOUS == 1 && -z $TARGET_SHA ]] && TARGET_SHA=$(sed -n 's/^PREVIOUS_SHA=//p' "$state_file")
require_sha "$TARGET_SHA"
export APP_IMAGE_TAG=$TARGET_SHA
acquire_lock; validate_identity; validate_dependencies; validate_env_file
grep -Eq "(^| )deployed=$TARGET_SHA( |$)|^ACTIVE_SHA=$TARGET_SHA$|^PREVIOUS_SHA=$TARGET_SHA$" "$RUNTIME_PATH/deployments.log" "$state_file" || die "SHA_NOT_PREVIOUSLY_DEPLOYED"
docker image inspect "${APP_IMAGE_REPOSITORY:-emporio-pedidos-producao}:$TARGET_SHA" >/dev/null 2>&1 || die "ROLLBACK_IMAGE_MISSING"
current=$(sed -n 's/^ACTIVE_SHA=//p' "$state_file")
applied=$(sed -n 's/^MIGRATIONS_APPLIED=//p' "$state_file")
if [[ ${applied:-0} != 0 && ${applied:-unknown} != unknown ]]; then
  info "DB_ROLLBACK_DECISION_REQUIRED=SIM"
  die "MIGRATIONS_WERE_APPLIED_DATABASE_DOWNGRADE_REFUSED"
fi
info "DATABASE_RESTORE=NEVER_AUTOMATIC"
run rollback compose up -d --no-build web worker
if [[ $DRY_RUN != 1 ]]; then
  for _ in {1..10}; do curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8850/health/ >/dev/null; done
  curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8850/conta/entrar/ >/dev/null
  [[ $(container_restart_count web) == 0 && $(container_restart_count worker) == 0 ]] || die "RESTART_COUNT_NONZERO"
  printf 'ACTIVE_SHA=%s\nPREVIOUS_SHA=%s\nIMAGE=%s:%s\n' "$TARGET_SHA" "$current" "${APP_IMAGE_REPOSITORY:-emporio-pedidos-producao}" "$TARGET_SHA" >"$state_file"; chmod 600 "$state_file"
  printf '%s previous=%s deployed=%s rollback=yes result=success\n' "$(timestamp)" "$current" "$TARGET_SHA" >>"$RUNTIME_PATH/deployments.log"
  write_evidence "rollback-$TARGET_SHA.txt" "timestamp=$(timestamp) from=$current to=$TARGET_SHA database_restore=no result=success"
fi
info "ROLLBACK=SUCCESS"
