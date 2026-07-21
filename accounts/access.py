from __future__ import annotations

from enum import StrEnum

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from .roles import (
    ROLE_ADMIN,
    ROLE_ATTENDANCE,
    ROLE_EXPEDITION,
    ROLE_FINANCE,
    ROLE_PRODUCTION,
    ROLE_SUPPORT,
    ROLE_SYSTEM_ADMIN,
)

ROOT_USERNAME = "ti"


class Capability(StrEnum):
    VIEW_ORDERS = "view_orders"
    CREATE_ORDERS = "create_orders"
    EDIT_ORDERS = "edit_orders"
    CHANGE_ORDER_STATUS = "change_order_status"
    CANCEL_ORDERS = "cancel_orders"
    APPROVE_REQUESTS = "approve_requests"
    REJECT_REQUESTS = "reject_requests"
    REQUEST_CORRECTION = "request_correction"
    VIEW_CUSTOMERS = "view_customers"
    VIEW_REPORTS = "view_reports"
    VIEW_AUDIT = "view_audit"
    MANAGE_ATTENDANTS = "manage_attendants"
    ACCESS_TECHNICAL_AREA = "access_technical_area"
    MANAGE_LOWER_USERS = "manage_lower_users"
    MANAGE_SYSTEM_ADMINS = "manage_system_admins"
    VIEW_ALL_USERS = "view_all_users"
    ACCESS_ADMIN_SETTINGS = "access_admin_settings"
    ACCESS_ALL_OPERATIONS = "access_all_operations"


DIRECTOR_CAPABILITIES = frozenset(
    {
        Capability.VIEW_ORDERS,
        Capability.CREATE_ORDERS,
        Capability.EDIT_ORDERS,
        Capability.CHANGE_ORDER_STATUS,
        Capability.CANCEL_ORDERS,
        Capability.APPROVE_REQUESTS,
        Capability.REJECT_REQUESTS,
        Capability.REQUEST_CORRECTION,
        Capability.VIEW_CUSTOMERS,
        Capability.VIEW_REPORTS,
        Capability.VIEW_AUDIT,
        Capability.MANAGE_ATTENDANTS,
    }
)

ALL_CAPABILITIES = frozenset(Capability)
SYSTEM_ADMIN_CAPABILITIES = ALL_CAPABILITIES - {Capability.MANAGE_SYSTEM_ADMINS}

ATTENDANT_CAPABILITIES = frozenset(
    {
        Capability.VIEW_ORDERS,
        Capability.CREATE_ORDERS,
        Capability.CHANGE_ORDER_STATUS,
        Capability.CANCEL_ORDERS,
        Capability.APPROVE_REQUESTS,
        Capability.REQUEST_CORRECTION,
        Capability.VIEW_CUSTOMERS,
    }
)

ROLE_CAPABILITIES = {
    ROLE_SYSTEM_ADMIN: SYSTEM_ADMIN_CAPABILITIES,
    ROLE_ADMIN: DIRECTOR_CAPABILITIES,
    ROLE_ATTENDANCE: ATTENDANT_CAPABILITIES,
    ROLE_PRODUCTION: frozenset(
        {Capability.VIEW_ORDERS, Capability.CHANGE_ORDER_STATUS}
    ),
    ROLE_EXPEDITION: frozenset(
        {Capability.VIEW_ORDERS, Capability.CHANGE_ORDER_STATUS}
    ),
    ROLE_FINANCE: frozenset(
        {
            Capability.VIEW_ORDERS,
            Capability.VIEW_REPORTS,
            Capability.VIEW_AUDIT,
        }
    ),
    ROLE_SUPPORT: frozenset({Capability.ACCESS_TECHNICAL_AREA}),
}


def is_root_system_admin(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "username", None) == ROOT_USERNAME
        and getattr(user, "is_superuser", False)
    )

COMPATIBILITY_PERMISSIONS = {
    Capability.VIEW_ORDERS: frozenset(
        {
            "orders.view_order",
            "customer_portal.review_customerorderrequest",
        }
    ),
}


def user_has_capability(user, capability: Capability) -> bool:
    if not user.is_authenticated or not user.is_active:
        return False
    if is_root_system_admin(user):
        return True
    role_names = user.groups.values_list("name", flat=True)
    if any(capability in ROLE_CAPABILITIES.get(role, ()) for role in role_names):
        return True
    permissions = COMPATIBILITY_PERMISSIONS.get(capability, ())
    return any(user.has_perm(permission) for permission in permissions)


class CapabilityRequiredMixin(LoginRequiredMixin):
    capability_required: Capability

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not user_has_capability(request.user, self.capability_required):
            raise PermissionDenied("Seu perfil não permite acessar este recurso.")
        return super().dispatch(request, *args, **kwargs)
