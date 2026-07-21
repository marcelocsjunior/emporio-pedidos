from __future__ import annotations

from accounts.access import Capability, user_has_capability
from accounts.roles import (
    ROLE_ADMIN,
    ROLE_ATTENDANCE,
    ROLE_EXPEDITION,
    ROLE_PRODUCTION,
)

from .models import Order

ROLE_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    ROLE_ATTENDANCE: {
        Order.Status.PENDING: {Order.Status.RECEIVED, Order.Status.CANCELLED},
        Order.Status.RECEIVED: {Order.Status.CANCELLED},
    },
    ROLE_PRODUCTION: {
        Order.Status.RECEIVED: {Order.Status.IN_PRODUCTION},
    },
    ROLE_EXPEDITION: {
        Order.Status.IN_PRODUCTION: {Order.Status.OUT_FOR_DELIVERY},
        Order.Status.OUT_FOR_DELIVERY: {Order.Status.DELIVERED},
    },
}


def allowed_statuses_for_user(user, order: Order) -> set[str]:
    if not user_has_capability(user, Capability.CHANGE_ORDER_STATUS):
        return set()
    roles = set(user.groups.values_list("name", flat=True))
    if user.is_superuser or ROLE_ADMIN in roles:
        from .services import ALLOWED_TRANSITIONS

        return set(ALLOWED_TRANSITIONS[order.status])

    allowed: set[str] = set()
    for role in roles:
        allowed.update(ROLE_TRANSITIONS.get(role, {}).get(order.status, set()))
    return allowed
