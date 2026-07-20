from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction

from orders.services import record_audit

from .access import ROOT_USERNAME, Capability, is_root_system_admin, user_has_capability
from .roles import (
    ROLE_ADMIN,
    ROLE_ATTENDANCE,
    ROLE_EXPEDITION,
    ROLE_FINANCE,
    ROLE_PRODUCTION,
    ROLE_SUPPORT,
    ROLE_SYSTEM_ADMIN,
)

MANAGED_ROLE_NAMES = (
    ROLE_SYSTEM_ADMIN,
    ROLE_ADMIN,
    ROLE_ATTENDANCE,
    ROLE_SUPPORT,
    ROLE_PRODUCTION,
    ROLE_EXPEDITION,
    ROLE_FINANCE,
)

VISIBLE_ROLE_NAMES = {
    ROLE_ADMIN: "Proprietária / Diretora",
    ROLE_ATTENDANCE: "Atendente",
}


def display_role(user) -> str:
    if is_root_system_admin(user):
        return "Administrador Raiz do Sistema"
    role = user.groups.filter(name__in=MANAGED_ROLE_NAMES).values_list("name", flat=True).first()
    return VISIBLE_ROLE_NAMES.get(role, role or "Sem perfil interno")


def user_role(user) -> str | None:
    return user.groups.filter(name__in=MANAGED_ROLE_NAMES).values_list("name", flat=True).first()


def roles_actor_can_assign(actor) -> tuple[str, ...]:
    if is_root_system_admin(actor):
        return MANAGED_ROLE_NAMES
    if user_has_capability(actor, Capability.MANAGE_LOWER_USERS):
        return tuple(role for role in MANAGED_ROLE_NAMES if role != ROLE_SYSTEM_ADMIN)
    if user_has_capability(actor, Capability.MANAGE_ATTENDANTS):
        return (ROLE_ATTENDANCE,)
    return ()


def can_manage_user(actor, target) -> bool:
    if target.username == ROOT_USERNAME:
        return False
    target_role = user_role(target)
    if target_role == ROLE_SYSTEM_ADMIN:
        return is_root_system_admin(actor)
    return target_role in roles_actor_can_assign(actor)


def audit_denied(*, actor, target, action: str, reason: str) -> None:
    record_audit(
        actor=actor,
        action=action,
        entity=target,
        payload={"denied": True, "reason": reason},
    )


def assert_can_manage(actor, target, *, action: str = "user.change_denied") -> None:
    if can_manage_user(actor, target):
        return
    audit_denied(actor=actor, target=target, action=action, reason="target_out_of_scope")
    raise PermissionDenied("Seu perfil não pode administrar esta conta.")


@transaction.atomic
def toggle_user_active(*, actor, target) -> None:
    locked = type(target).objects.select_for_update().get(pk=target.pk)
    assert_can_manage(actor, locked, action="user.suspension_denied")
    locked.is_active = not locked.is_active
    locked.is_staff = False
    locked.is_superuser = False
    locked.save(update_fields=("is_active", "is_staff", "is_superuser"))
    record_audit(
        actor=actor,
        action="user.reactivated" if locked.is_active else "user.suspended",
        entity=locked,
        payload={"active": locked.is_active, "role": display_role(locked)},
    )


@transaction.atomic
def require_password_change(*, actor, target) -> None:
    locked = type(target).objects.select_for_update().get(pk=target.pk)
    assert_can_manage(actor, locked, action="user.password_change_denied")
    locked.must_change_password = True
    locked.is_staff = False
    locked.is_superuser = False
    locked.save(update_fields=("must_change_password", "is_staff", "is_superuser"))
    record_audit(actor=actor, action="user.password_change_required", entity=locked)
