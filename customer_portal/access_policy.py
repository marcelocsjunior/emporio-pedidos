from __future__ import annotations

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

DEFAULT_CUSTOMER_ACCESS_MANAGER_USERNAMES = frozenset({"angela", "suporte", "ti"})


def customer_access_manager_usernames() -> frozenset[str]:
    configured = getattr(
        settings,
        "CUSTOMER_ACCESS_MANAGER_USERNAMES",
        DEFAULT_CUSTOMER_ACCESS_MANAGER_USERNAMES,
    )
    if isinstance(configured, str):
        configured = configured.split(",")
    return frozenset(
        str(username).strip().casefold()
        for username in configured
        if str(username).strip()
    )


def can_manage_customer_access(user) -> bool:
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    username = str(getattr(user, "username", "")).strip().casefold()
    return username in customer_access_manager_usernames()


class CustomerAccessManagerMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not can_manage_customer_access(request.user):
            raise PermissionDenied(
                "Somente os responsáveis designados podem administrar acessos de clientes."
            )
        return super().dispatch(request, *args, **kwargs)
