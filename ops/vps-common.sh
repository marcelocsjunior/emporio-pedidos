#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly EXPECTED_REMOTE="https://github.com/marcelocsjunior/emporio-pedidos.git"
readonly EXPECTED_APP_PATH="/opt/emporio-pedidos-producao/app"
readonly EXPECTED_RUNTIME_PATH="/opt/emporio-pedidos-producao/runtime"
readonly EXPECTED_BACKUP_PATH="/opt/emporio-pedidos-producao/backups"
readonly EXPECTED_LOG_PATH="/opt/emporio-pedidos-producao/logs"
readonly EXPECTED_PROJECT="emporio_pedidos_producao"
readonly EXPECTED_PORT="8850"
readonly EXPECTED_VOLUME="emporio_pedidos_producao_pgdata"
readonly PILOT_MARKERS='8020|emporio_pedidos_vps_teste|/opt/emporio-pedidos-teste|emporio_pedidos_vps_teste_emporio_pgdata'

DRY_RUN=${DRY_RUN:-0}
PREFLIGHT_ONLY=${PREFLIGHT_ONLY:-0}
APP_PATH=${APP_PATH:-$EXPECTED_APP_PATH}
RUNTIME_PATH=${RUNTIME_PATH:-$EXPECTED_RUNTIME_PATH}
BACKUP_PATH=${BACKUP_PATH:-$EXPECTED_BACKUP_PATH}
LOG_PATH=${LOG_PATH:-$EXPECTED_LOG_PATH}
ENV_FILE=${ENV_FILE:-$RUNTIME_PATH/.env}
COMPOSE_FILE=${COMPOSE_FILE:-$APP_PATH/deploy/docker-compose.vps.yml}
LOCK_FILE=${LOCK_FILE:-$RUNTIME_PATH/deploy.lock}

timestamp() { date --iso-8601=seconds; }
log() { printf '%s [%s] %s\n' "$(timestamp)" "$1" "$2"; }
info() { log INFO "$*"; }
warn() { log WARN "$*"; }
die() { log ERROR "$*" >&2; return 1; }
sanitize() { sed -E 's/((PASSWORD|SECRET|TOKEN|KEY|COOKIE|SESSION)[^ =:]*)[=:][^ ]+/\1=[REDACTED]/Ig'; }
require_command() { command -v "$1" >/dev/null 2>&1 || die "DEPENDENCY_MISSING=$1"; }
is_full_sha() { [[ ${1:-} =~ ^[0-9a-f]{40}$ ]]; }
require_sha() { is_full_sha "${1:-}" || die "SHA_INVALID=expected_full_40_character_sha"; }

assert_no_pilot_marker() {
  local value=${1:-}
  ! printf '%s' "$value" | grep -Eq "$PILOT_MARKERS" || die "PILOT_PROTECTION=BLOCKED"
}

validate_identity() {
  [[ $APP_PATH == "$EXPECTED_APP_PATH" ]] || die "APP_PATH_INVALID"
  [[ $RUNTIME_PATH == "$EXPECTED_RUNTIME_PATH" ]] || die "RUNTIME_PATH_INVALID"
  [[ $BACKUP_PATH == "$EXPECTED_BACKUP_PATH" ]] || die "BACKUP_PATH_INVALID"
  [[ $LOG_PATH == "$EXPECTED_LOG_PATH" ]] || die "LOG_PATH_INVALID"
  [[ ${COMPOSE_PROJECT_NAME:-$EXPECTED_PROJECT} == "$EXPECTED_PROJECT" ]] || die "COMPOSE_PROJECT_INVALID"
  [[ ${APP_PORT:-$EXPECTED_PORT} == "$EXPECTED_PORT" ]] || die "APP_PORT_INVALID"
  [[ ${DB_VOLUME_NAME:-$EXPECTED_VOLUME} == "$EXPECTED_VOLUME" ]] || die "DB_VOLUME_INVALID"
  assert_no_pilot_marker "$APP_PATH $RUNTIME_PATH $BACKUP_PATH $LOG_PATH ${COMPOSE_PROJECT_NAME:-} ${APP_PORT:-} ${DB_VOLUME_NAME:-} $COMPOSE_FILE"
  info "PILOT_PROTECTION=ENABLED"
}

validate_host() {
  local expected actual
  expected=$(env_value DEPLOY_HOST_ID)
  [[ -n $expected && $expected != *'*'* && $expected != *'?'* ]] || die "HOST_ID_MISSING_OR_INVALID"
  actual=$(hostname -s)
  [[ $actual == "$expected" ]] || die "HOST_ID_MISMATCH"
  info "HOST_ID_EXPECTED=$expected HOST_ID_VALIDATION=OK"
}

validate_dependencies() {
  local command
  for command in docker git flock curl sha256sum stat awk sed grep; do require_command "$command"; done
  docker compose version >/dev/null 2>&1 || die "DOCKER_COMPOSE_UNAVAILABLE"
}

validate_capacity() {
  local disk_kb memory_kb cpus
  disk_kb=$(df -Pk "$APP_PATH" | awk 'NR==2 {print $4}')
  memory_kb=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
  cpus=$(getconf _NPROCESSORS_ONLN)
  ((disk_kb >= 2097152)) || die "DISK_CAPACITY_INSUFFICIENT"
  ((memory_kb >= 524288)) || die "MEMORY_CAPACITY_INSUFFICIENT"
  ((cpus >= 1)) || die "CPU_CAPACITY_INSUFFICIENT"
}

validate_port_owner() {
  local owners
  owners=$(docker ps --filter "publish=$EXPECTED_PORT" --format '{{.Label "com.docker.compose.project"}}' | sort -u)
  [[ -z $owners || $owners == "$EXPECTED_PROJECT" ]] || die "APP_PORT_OWNED_BY_ANOTHER_PROJECT"
}

container_restart_count() {
  local service=$1 container_id
  container_id=$(compose ps -q "$service")
  [[ -n $container_id ]] || die "CONTAINER_MISSING=$service"
  docker inspect --format '{{.RestartCount}}' "$container_id"
}

validate_env_file() {
  [[ -f $ENV_FILE ]] || die "ENV_FILE_MISSING"
  local mode
  mode=$(stat -c '%a' "$ENV_FILE")
  [[ $mode == 600 || $mode == 400 ]] || die "ENV_FILE_PERMISSIONS_INVALID"
  grep -Eq '^APP_PORT=8850$' "$ENV_FILE" || die "ENV_APP_PORT_INVALID"
  grep -Eq '^COMPOSE_PROJECT_NAME=emporio_pedidos_producao$' "$ENV_FILE" || die "ENV_PROJECT_INVALID"
  grep -Eq '^DB_VOLUME_NAME=emporio_pedidos_producao_pgdata$' "$ENV_FILE" || die "ENV_VOLUME_INVALID"
  grep -Eq '^AI_ENABLED=0$' "$ENV_FILE" || die "AI_MUST_BE_DISABLED"
  grep -Eq '^AI_ACTIVE_ASSISTANT_ENABLED=0$' "$ENV_FILE" || die "ACTIVE_AI_MUST_BE_DISABLED"
  ! grep -Eq "$PILOT_MARKERS" "$ENV_FILE" || die "PILOT_PROTECTION=BLOCKED"
  validate_secrets
  validate_public_http
}

env_value() {
  local key=$1 count
  count=$(awk -F= -v key="$key" '$1 == key {count++} END {print count+0}' "$ENV_FILE")
  [[ $count == 1 ]] || die "ENV_KEY_INVALID=$key"
  awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"
}

validate_secrets() {
  local secret password lower
  secret=$(env_value DJANGO_SECRET_KEY); password=$(env_value POSTGRES_PASSWORD)
  [[ ${#secret} -ge 50 && $secret != "$password" && $secret != *[[:space:]]* ]] || die "DJANGO_SECRET_KEY_INVALID"
  [[ ${#password} -ge 24 && $password != *[[:space:]]* ]] || die "POSTGRES_PASSWORD_INVALID"
  [[ $password != *"aaaaaaaaaaaaaaaaaaaaaaaa"* && $password != *"000000000000000000000000"* ]] || die "POSTGRES_PASSWORD_PREDICTABLE"
  lower=$(printf '%s\n%s' "$secret" "$password" | tr '[:upper:]' '[:lower:]')
  ! grep -Eq 'generate-a-new|change-me|troque|example|placeholder|default-password|set-by-deploy|password123|secret123' <<<"$lower" || die "PLACEHOLDER_OR_PREDICTABLE_SECRET_REFUSED"
  info "DJANGO_SECRET_KEY_VALID=SIM"
  info "POSTGRES_PASSWORD_VALID=SIM"
}

validate_public_http() {
  [[ $(env_value APP_PORT) == 8850 ]] || die "PUBLIC_HTTP_PORT_INVALID"
  [[ $(env_value APP_BIND_HOST) == 0.0.0.0 ]] || die "PUBLIC_HTTP_BIND_INVALID"
  [[ $(env_value DJANGO_DEBUG) == 0 ]] || die "DEBUG_MUST_BE_ZERO"
  local hosts origins
  hosts=$(env_value DJANGO_ALLOWED_HOSTS); origins=$(env_value DJANGO_CSRF_TRUSTED_ORIGINS)
  [[ $hosts != *'*'* && ",$hosts," == *",149.28.115.193,"* ]] || die "ALLOWED_HOSTS_INVALID"
  [[ $origins == http://149.28.115.193:8850 ]] || die "CSRF_TRUSTED_ORIGINS_INVALID"
  [[ $(env_value DJANGO_SESSION_COOKIE_SECURE) == 0 ]] || die "SESSION_COOKIE_MODE_INVALID"
  [[ $(env_value DJANGO_CSRF_COOKIE_SECURE) == 0 ]] || die "CSRF_COOKIE_MODE_INVALID"
  info "PUBLIC_HTTP_MODE=ENABLED"
  info "PUBLIC_URL=http://149.28.115.193:8850"
  info "CSRF=ENABLED DEBUG=0"
}

validate_remote() {
  local remote
  remote=$(git -C "$APP_PATH" remote get-url origin)
  [[ $remote == "$EXPECTED_REMOTE" || $remote == git@github.com:marcelocsjunior/emporio-pedidos.git ]] || die "GIT_REMOTE_INVALID"
}

validate_worktree() {
  [[ -z $(git -C "$APP_PATH" status --porcelain=v1 --untracked-files=all) ]] || die "GIT_WORKTREE_DIRTY"
  [[ -z $(git -C "$APP_PATH" submodule status 2>/dev/null | grep -E '^[+-U]' || true) ]] || die "GIT_SUBMODULE_DIRTY"
  info "GIT_WORKTREE_CLEAN=SIM"
}

prepare_runtime() {
  if [[ $DRY_RUN == 1 ]]; then info "DRY_RUN=create_secure_runtime_directories"; return; fi
  install -d -m 700 "$RUNTIME_PATH" "$RUNTIME_PATH/state" "$RUNTIME_PATH/evidence" "$BACKUP_PATH" "$LOG_PATH"
  touch "$RUNTIME_PATH/deployments.log"; chmod 600 "$RUNTIME_PATH/deployments.log"
}

acquire_lock() {
  [[ ${OPERATION_LOCK_HELD:-0} == 1 ]] && return
  prepare_runtime
  if [[ $DRY_RUN == 1 ]]; then info "DRY_RUN=lock"; return; fi
  exec 9>"$LOCK_FILE"
  flock -n 9 || die "OPERATION_ALREADY_RUNNING"
  chmod 600 "$LOCK_FILE"
  export OPERATION_LOCK_HELD=1
}

compose() {
  APP_IMAGE_TAG=${APP_IMAGE_TAG:?} VPS_ENV_FILE=$ENV_FILE COMPOSE_PROJECT_NAME=$EXPECTED_PROJECT APP_PORT=$EXPECTED_PORT DB_VOLUME_NAME=$EXPECTED_VOLUME \
    docker compose --project-name "$EXPECTED_PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

run() {
  local label=${1:?run requires a label}; shift
  (($#)) || die "RUN_COMMAND_MISSING=$label"
  if [[ $DRY_RUN == 1 ]]; then
    printf 'DRY_RUN_LABEL=%q COMMAND=' "$label"; printf '%q ' "$@"; printf '\n'
  else
    "$@"
  fi
}

write_evidence() {
  local name content target
  name=$1
  content=$2
  target="$RUNTIME_PATH/evidence/$name"
  [[ $DRY_RUN == 1 ]] && { info "DRY_RUN=evidence:$name"; return; }
  printf '%s\n' "$content" | sanitize >"$target"; chmod 600 "$target"
}
