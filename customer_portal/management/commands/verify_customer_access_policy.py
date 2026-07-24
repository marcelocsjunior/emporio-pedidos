from __future__ import annotations

from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from customer_portal.access_policy import (
    CustomerAccessManagerMixin,
    can_manage_customer_access,
    customer_access_manager_usernames,
)
from customer_portal.access_views import (
    AccessRequestQueueView,
    AccessRequestReviewView,
    PortalAccessDetailView,
    PortalAccessListView,
    PortalAccessStatusView,
    PortalPasswordResetView,
    PortalUserCreateView,
    PortalUserLinkView,
)

EXPECTED_USERNAMES = frozenset({"angela", "suporte", "ti"})
REQUIRED_EXISTING_USERNAMES = frozenset({"angela", "ti"})
PROTECTED_VIEWS = (
    PortalAccessListView,
    PortalAccessDetailView,
    PortalUserCreateView,
    PortalUserLinkView,
    PortalAccessStatusView,
    PortalPasswordResetView,
    AccessRequestQueueView,
    AccessRequestReviewView,
)


class Command(BaseCommand):
    help = "Valida, sem escrever no banco, a política nominal de acessos dos clientes."

    def handle(self, *args, **options):
        configured = customer_access_manager_usernames()
        if configured != EXPECTED_USERNAMES:
            raise CommandError(
                "lista configurada divergente: "
                f"esperado={sorted(EXPECTED_USERNAMES)} atual={sorted(configured)}"
            )

        for username in EXPECTED_USERNAMES:
            principal = SimpleNamespace(
                is_authenticated=True,
                is_active=True,
                username=username,
            )
            if not can_manage_customer_access(principal):
                raise CommandError(f"usuário nominal sintético foi negado: {username}")

        non_designated = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            username="nao_designado",
        )
        if can_manage_customer_access(non_designated):
            raise CommandError("usuário não designado recebeu autorização")

        inactive_designated = SimpleNamespace(
            is_authenticated=True,
            is_active=False,
            username="suporte",
        )
        if can_manage_customer_access(inactive_designated):
            raise CommandError("usuário designado inativo recebeu autorização")

        for view_class in PROTECTED_VIEWS:
            if not issubclass(view_class, CustomerAccessManagerMixin):
                raise CommandError(
                    f"view sem política nominal: {view_class.__module__}.{view_class.__name__}"
                )

        User = get_user_model()
        matches = [
            user
            for user in User.objects.filter(is_active=True).only(
                "id", "username", "is_active", "must_change_password"
            )
            if user.username.casefold() in EXPECTED_USERNAMES
        ]
        normalized = [user.username.casefold() for user in matches]
        duplicates = sorted(
            username for username in set(normalized) if normalized.count(username) > 1
        )
        if duplicates:
            raise CommandError(f"usuários nominais duplicados por caixa: {duplicates}")

        existing = {user.username.casefold(): user for user in matches}
        missing_required = sorted(REQUIRED_EXISTING_USERNAMES - set(existing))
        if missing_required:
            raise CommandError(
                f"contas obrigatórias ausentes ou inativas: {missing_required}"
            )

        for username, user in existing.items():
            if not can_manage_customer_access(user):
                raise CommandError(f"conta ativa designada foi negada: {username}")
            self.stdout.write(
                f"USER_{username.upper()}=ACTIVE;MUST_CHANGE_PASSWORD="
                f"{int(user.must_change_password)};BACKEND_AUTHORIZED=1"
            )

        support_status = (
            "PRESENT_ACTIVE"
            if "suporte" in existing
            else "ABSENT_ALLOWED"
        )
        self.stdout.write(f"SUPPORT_ACCOUNT={support_status}")
        self.stdout.write(
            "CUSTOMER_ACCESS_POLICY_BACKEND=OK; "
            "ALLOWED=angela,suporte,ti; "
            f"SUPPORT_ACCOUNT={support_status}; "
            "PASSWORD_REDIRECT_HTTP_NOT_USED=1; DATA_WRITES=ZERO"
        )
