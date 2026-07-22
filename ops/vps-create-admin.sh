#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/vps-common.sh"
[[ -t 0 && -t 1 ]] || die "INTERACTIVE_TERMINAL_REQUIRED"
validate_identity; validate_dependencies; validate_env_file
APP_IMAGE_TAG=$(sed -n 's/^ACTIVE_SHA=//p' "$RUNTIME_PATH/state/active.env"); export APP_IMAGE_TAG
require_sha "$APP_IMAGE_TAG"
count=$(compose run --rm web python manage.py shell -c "from django.contrib.auth import get_user_model; print(get_user_model().objects.filter(is_superuser=True).count())" | tail -n1)
[[ $count == 0 ]] || die "SUPERUSER_ALREADY_EXISTS"
read -r -p 'Criar o administrador inicial nesta implantação isolada? [sim/N] ' answer
[[ $answer == sim ]] || die "ADMIN_CREATION_CANCELLED"
compose run --rm web python manage.py createsuperuser
printf '%s admin_created=yes\n' "$(timestamp)" >>"$RUNTIME_PATH/deployments.log"
info "ADMIN_CREATED=SIM"
