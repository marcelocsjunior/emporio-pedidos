from __future__ import annotations

from collections.abc import Iterable

from django.contrib.auth.models import Group, Permission
from django.db import transaction

ROLE_ADMIN = "Administrador"
ROLE_SYSTEM_ADMIN = "Administrador do Sistema"
ROLE_ATTENDANCE = "Atendimento"
ROLE_PRODUCTION = "Produção"
ROLE_EXPEDITION = "Expedição"
ROLE_FINANCE = "Financeiro"
ROLE_SUPPORT = "Desenvolvimento / Suporte"

ROLE_NAMES = (
    ROLE_SYSTEM_ADMIN,
    ROLE_ADMIN,
    ROLE_ATTENDANCE,
    ROLE_PRODUCTION,
    ROLE_EXPEDITION,
    ROLE_FINANCE,
    ROLE_SUPPORT,
)

PermissionSpec = tuple[str, str]


def _model_permissions(app_label: str, model: str, actions: Iterable[str]) -> set[PermissionSpec]:
    return {(app_label, f"{action}_{model}") for action in actions}


ORDER_READ = {
    *_model_permissions("orders", "company", ("view",)),
    *_model_permissions("orders", "product", ("view",)),
    *_model_permissions("orders", "order", ("view",)),
    *_model_permissions("orders", "orderitem", ("view",)),
    *_model_permissions("orders", "orderstatushistory", ("view",)),
}

AI_FEEDBACK = {
    *_model_permissions("intelligence", "airecommendation", ("view",)),
    *_model_permissions("intelligence", "aifeedback", ("add", "change", "view")),
}

PORTAL_REVIEW = {
    *_model_permissions("customer_portal", "customerportalaccess", ("view",)),
    *_model_permissions("customer_portal", "customerdeliverylocation", ("view",)),
    *_model_permissions("customer_portal", "customerorderrequest", ("change", "view")),
    *_model_permissions("customer_portal", "customerorderrequestitem", ("view",)),
    ("customer_portal", "review_customerorderrequest"),
}

ROLE_PERMISSION_MAP: dict[str, set[PermissionSpec]] = {
    ROLE_ADMIN: {
        *_model_permissions("accounts", "user", ("add", "change", "view")),
        *_model_permissions("orders", "company", ("add", "change", "view")),
        *_model_permissions("orders", "product", ("add", "change", "view")),
        *_model_permissions("orders", "order", ("add", "change", "view")),
        *_model_permissions("orders", "orderitem", ("add", "change", "delete", "view")),
        *_model_permissions("orders", "orderstatushistory", ("add", "view")),
        *_model_permissions("orders", "monthlyclosing", ("add", "change", "view")),
        *_model_permissions("orders", "auditevent", ("view",)),
        *_model_permissions("intelligence", "aievent", ("add", "change", "view")),
        *_model_permissions("intelligence", "aianalysisrun", ("view",)),
        *_model_permissions("intelligence", "airecommendation", ("add", "change", "view")),
        *_model_permissions("intelligence", "aifeedback", ("add", "change", "view")),
        *_model_permissions("intelligence", "aipromptversion", ("add", "change", "view")),
        *_model_permissions("intelligence", "aiusage", ("view",)),
        *_model_permissions(
            "customer_portal",
            "customerportalaccess",
            ("add", "change", "delete", "view"),
        ),
        *_model_permissions(
            "customer_portal",
            "customerdeliverylocation",
            ("add", "change", "delete", "view"),
        ),
        *_model_permissions(
            "customer_portal",
            "customerorderrequest",
            ("add", "change", "delete", "view"),
        ),
        *_model_permissions(
            "customer_portal",
            "customerorderrequestitem",
            ("add", "change", "delete", "view"),
        ),
        ("intelligence", "view_ai_delay"),
        ("intelligence", "view_ai_duplicate"),
        ("intelligence", "view_ai_production"),
        ("intelligence", "view_ai_finance"),
        ("intelligence", "process_ai_events"),
        ("customer_portal", "review_customerorderrequest"),
    },
    ROLE_ATTENDANCE: {
        *_model_permissions("orders", "company", ("add", "change", "view")),
        *_model_permissions("orders", "product", ("add", "change", "view")),
        *_model_permissions("orders", "order", ("add", "change", "view")),
        *_model_permissions("orders", "orderitem", ("add", "change", "delete", "view")),
        *_model_permissions("orders", "orderstatushistory", ("add", "view")),
        *PORTAL_REVIEW,
        *AI_FEEDBACK,
        ("intelligence", "view_ai_delay"),
        ("intelligence", "view_ai_duplicate"),
    },
    ROLE_PRODUCTION: {
        *ORDER_READ,
        *_model_permissions("orders", "order", ("change",)),
        *_model_permissions("orders", "orderstatushistory", ("add",)),
        *AI_FEEDBACK,
        ("intelligence", "view_ai_delay"),
        ("intelligence", "view_ai_production"),
    },
    ROLE_EXPEDITION: {
        *ORDER_READ,
        *_model_permissions("orders", "order", ("change",)),
        *_model_permissions("orders", "orderstatushistory", ("add",)),
        *AI_FEEDBACK,
        ("intelligence", "view_ai_delay"),
    },
    ROLE_FINANCE: {
        *ORDER_READ,
        *_model_permissions("orders", "monthlyclosing", ("add", "change", "view")),
        *_model_permissions("orders", "auditevent", ("view",)),
        *AI_FEEDBACK,
        ("intelligence", "view_ai_finance"),
    },
    ROLE_SUPPORT: set(),
}

# O Administrador do Sistema recebe as permissões funcionais do perfil mais amplo,
# além da área técnica. A autorização para gerir perfis continua na camada de
# capacidades, não nas permissões genéricas do Django.
ROLE_PERMISSION_MAP[ROLE_SYSTEM_ADMIN] = {
    *(spec for spec in ROLE_PERMISSION_MAP[ROLE_ADMIN] if not spec[1].startswith("delete_")),
    *_model_permissions("accounts", "user", ("add", "change", "view")),
}


@transaction.atomic
def ensure_roles(*, strict: bool = True) -> dict[str, Group]:
    available = {
        (permission.content_type.app_label, permission.codename): permission
        for permission in Permission.objects.select_related("content_type").filter(
            content_type__app_label__in={
                "accounts",
                "orders",
                "intelligence",
                "customer_portal",
            }
        )
    }
    expected = set().union(*ROLE_PERMISSION_MAP.values())
    missing = sorted(expected - set(available))
    if strict and missing:
        missing_text = ", ".join(f"{app}.{codename}" for app, codename in missing)
        raise RuntimeError(f"Permissões ainda não disponíveis: {missing_text}")

    groups: dict[str, Group] = {}
    for role_name, permission_specs in ROLE_PERMISSION_MAP.items():
        group, _ = Group.objects.get_or_create(name=role_name)
        group.permissions.set(available[spec] for spec in permission_specs if spec in available)
        groups[role_name] = group
    return groups


def bootstrap_roles_after_migrate(sender, **kwargs) -> None:
    if sender.name in {"orders", "intelligence", "customer_portal"}:
        ensure_roles(strict=False)
