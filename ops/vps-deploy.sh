#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=ops/vps-common.sh
source "$SCRIPT_DIR/vps-common.sh"

REQUESTED_SHA=
while (($#)); do
  case $1 in
    --sha) REQUESTED_SHA=${2:-}; shift 2 ;;
    --preflight-only) PREFLIGHT_ONLY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) die "UNKNOWN_ARGUMENT" ;;
  esac
done
require_sha "$REQUESTED_SHA"
export APP_IMAGE_TAG=$REQUESTED_SHA
acquire_lock
validate_identity; validate_dependencies; validate_env_file; validate_host; validate_remote
validate_capacity; validate_port_owner
git -C "$APP_PATH" cat-file -e "$REQUESTED_SHA^{commit}" 2>/dev/null || die "AUTHORIZED_SHA_NOT_FOUND"
git -C "$APP_PATH" merge-base --is-ancestor "$REQUESTED_SHA" origin/main || die "FEATURE_SHA_REFUSED"
[[ $(git -C "$APP_PATH" rev-parse HEAD) == "$REQUESTED_SHA" ]] || die "HEAD_NOT_REQUESTED_SHA"
validate_worktree
compose config --quiet || die "COMPOSE_CONFIG_INVALID"
info "PREFLIGHT=OK"
[[ $PREFLIGHT_ONLY == 1 ]] && { info "RESULT=PREFLIGHT_ONLY"; exit 0; }

state_file="$RUNTIME_PATH/state/active.env"
active_sha=
[[ -f $state_file ]] && active_sha=$(sed -n 's/^ACTIVE_SHA=//p' "$state_file")
previous_image=
[[ -f $state_file ]] && previous_image=$(sed -n 's/^IMAGE=//p' "$state_file")
web_worker_changed=0
migration_risk=0
deploy_stage=preflight

deploy_failure() {
  local original_status=$1
  trap - ERR
  set +e
  warn "DEPLOY_FAILED_STAGE=$deploy_stage"
  if ((migration_risk != 0)); then
    info "AUTO_ROLLBACK=BLOCKED"
    info "DB_ROLLBACK_DECISION_REQUIRED=SIM"
  elif ((web_worker_changed == 1)) && is_full_sha "$active_sha" && [[ -n $previous_image ]] && docker image inspect "$previous_image" >/dev/null 2>&1 && compose ps --status running --services db | grep -qx db; then
    export APP_IMAGE_TAG=$active_sha
    if compose up -d --no-build web worker >/dev/null 2>&1; then
      rollback_ok=1
      for _ in {1..10}; do curl --fail --silent --max-time 5 http://127.0.0.1:8850/health/ >/dev/null || rollback_ok=0; done
      curl --fail --silent --max-time 5 http://127.0.0.1:8850/conta/entrar/ >/dev/null || rollback_ok=0
      [[ $(container_restart_count web) == 0 && $(container_restart_count worker) == 0 ]] || rollback_ok=0
      if ((rollback_ok == 1)); then
        info "AUTO_ROLLBACK=SUCCESS"
        info "DEPLOY_RESULT=FAILED_APPLICATION_RESTORED"
        write_evidence "auto-rollback-$REQUESTED_SHA.txt" "timestamp=$(timestamp) failed_sha=$REQUESTED_SHA restored_sha=$active_sha stage=$deploy_stage database_restore=no result=success"
      else
        info "AUTO_ROLLBACK=FAILED"; info "MANUAL_INTERVENTION_REQUIRED=SIM"
      fi
    else
      info "AUTO_ROLLBACK=FAILED"; info "MANUAL_INTERVENTION_REQUIRED=SIM"
    fi
  else
    info "AUTO_ROLLBACK=NOT_APPLICABLE"
  fi
  exit "$original_status"
}
trap 'deploy_failure $?' ERR
if [[ $active_sha == "$REQUESTED_SHA" ]] && compose ps --status running --services 2>/dev/null | grep -qx web && compose ps --status running --services 2>/dev/null | grep -qx worker && compose ps --status running --services 2>/dev/null | grep -qx db && curl --fail --silent --max-time 5 http://127.0.0.1:8850/health/ >/dev/null; then
  info "DEPLOY_MODE=NO_OP"; info "SHA_ALREADY_DEPLOYED=SIM"; info "MIGRATIONS_PENDING=ZERO"; info "SERVICES_HEALTHY=SIM"; info "CHANGES=ZERO"; exit 0
fi
mode=INSTALL
[[ -n $active_sha ]] && mode=UPDATE
[[ $active_sha == "$REQUESTED_SHA" ]] && mode=RECONCILE
info "DEPLOY_MODE=$mode"
if [[ $mode == UPDATE ]]; then "$SCRIPT_DIR/vps-backup.sh" --reason pre-update; fi
deploy_stage=build
image="${APP_IMAGE_REPOSITORY:-emporio-pedidos-producao}:$REQUESTED_SHA"
if ! docker image inspect "$image" >/dev/null 2>&1; then run build compose build web; fi
if [[ $DRY_RUN != 1 ]]; then
  [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image") == "$REQUESTED_SHA" ]] || die "IMAGE_REVISION_MISMATCH"
fi
run db compose up -d db
deploy_stage=database
if [[ $DRY_RUN != 1 ]]; then
  for _ in {1..30}; do [[ $(compose ps --format json db | grep -c 'healthy') -gt 0 ]] && break; sleep 2; done
fi
pending_before=unknown
if [[ $DRY_RUN != 1 ]]; then pending_before=$(compose run --rm web python manage.py showmigrations --plan | grep -c '^\[ \]' || true); fi
migration_risk=1
[[ $pending_before == 0 ]] && migration_risk=0
deploy_stage=migrations
run migrate compose run --rm web python manage.py migrate --noinput
if [[ $DRY_RUN == 1 || $pending_before == 0 ]]; then migration_risk=0; fi
run bootstrap_roles compose run --rm web python manage.py bootstrap_roles
deploy_stage=application
web_worker_changed=1
run services compose up -d --no-build web worker
if [[ $DRY_RUN != 1 ]]; then
  compose run --rm web python manage.py check
  pending_after=$(compose run --rm web python manage.py showmigrations --plan | grep -c '^\[ \]' || true)
  [[ $pending_after == 0 ]] || die "MIGRATIONS_PENDING=$pending_after"
  compose run --rm web python manage.py collectstatic --noinput --dry-run
  for _ in {1..10}; do curl --fail --silent --show-error --max-time 5 "http://127.0.0.1:8850/health/" >/dev/null; done
  curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8850/conta/entrar/ >/dev/null
  css_path=$(find "$APP_PATH/static" -type f -name '*.css' -printf '%P\n' | head -n1)
  [[ -n $css_path ]] || die "STATIC_CSS_NOT_FOUND"
  curl --fail --silent --show-error --max-time 5 "http://127.0.0.1:8850/static/$css_path" >/dev/null
  compose ps
  web_restarts=$(container_restart_count web); worker_restarts=$(container_restart_count worker); db_restarts=$(container_restart_count db)
  [[ $web_restarts == 0 && $worker_restarts == 0 && $db_restarts == 0 ]] || die "RESTART_COUNT_NONZERO"
  log_errors=$(compose logs --since 10m --no-color web worker 2>&1 | sanitize | grep -Eic 'HTTP 500|TemplateSyntaxError|NoReverseMatch|database error|critical|timeout' || true)
  [[ $log_errors == 0 ]] || die "LOG_VALIDATION_FAILED"
  admin_count=$(compose run --rm web python manage.py shell -c "from django.contrib.auth import get_user_model; print(get_user_model().objects.filter(is_superuser=True).count())" | tail -n1)
  [[ $admin_count -gt 0 ]] || info "ADMIN_REQUIRED=SIM"
  previous=${active_sha:-none}
  printf 'ACTIVE_SHA=%s\nPREVIOUS_SHA=%s\nIMAGE=%s:%s\nMIGRATIONS_APPLIED=%s\n' "$REQUESTED_SHA" "$previous" "${APP_IMAGE_REPOSITORY:-emporio-pedidos-producao}" "$REQUESTED_SHA" "$pending_before" >"$state_file"
  chmod 600 "$state_file"
  printf '%s previous=%s deployed=%s result=success\n' "$(timestamp)" "$previous" "$REQUESTED_SHA" >>"$RUNTIME_PATH/deployments.log"
  [[ $mode == INSTALL ]] && "$SCRIPT_DIR/vps-backup.sh" --reason baseline
  ids=$(compose ps -q | tr '\n' ',' | sed 's/,$//')
  write_evidence "deploy-$REQUESTED_SHA.txt" "timestamp=$(timestamp) previous_sha=$previous requested_sha=$REQUESTED_SHA deployed_sha=$REQUESTED_SHA image=$image containers=$ids volume=$EXPECTED_VOLUME migrations_pending=$pending_after migrations_applied=$pending_before restart_counts=$db_restarts,$web_restarts,$worker_restarts healthchecks=10 login_http=200 static_http=200 http_500=0 result=success"
fi
trap - ERR
info "RESULT=SUCCESS"
