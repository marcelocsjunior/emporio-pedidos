from __future__ import annotations

from dataclasses import dataclass
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
    ACCESS_DASHBOARD = "access_dashboard"
    VIEW_ORDERS = "view_orders"
    CREATE_ORDERS = "create_orders"
    EDIT_ORDERS = "edit_orders"
    CHANGE_ORDER_STATUS = "change_order_status"
    CANCEL_ORDERS = "cancel_orders"
    VIEW_REQUESTS = "view_requests"
    APPROVE_REQUESTS = "approve_requests"
    REJECT_REQUESTS = "reject_requests"
    REQUEST_CORRECTION = "request_correction"
    VIEW_COMPANIES = "view_companies"
    MANAGE_COMPANIES = "manage_companies"
    VIEW_PRODUCTS = "view_products"
    MANAGE_PRODUCTS = "manage_products"
    VIEW_CLOSINGS = "view_closings"
    REVIEW_CLOSINGS = "review_closings"
    EXPORT_CLOSINGS = "export_closings"
    VIEW_REPORTS = "view_reports"
    VIEW_AUDIT = "view_audit"
    ACCESS_INTELLIGENCE = "access_intelligence"
    RECORD_AI_FEEDBACK = "record_ai_feedback"
    MANAGE_ATTENDANTS = "manage_attendants"
    MANAGE_LOWER_USERS = "manage_lower_users"
    ACCESS_TECHNICAL_AREA = "access_technical_area"
    MANAGE_SYSTEM_ADMINS = "manage_system_admins"
    VIEW_ALL_USERS = "view_all_users"
    ACCESS_ADMIN_SETTINGS = "access_admin_settings"
    ACCESS_ALL_OPERATIONS = "access_all_operations"

    # Aliases kept for call sites from MVP-ACESSO-01.
    VIEW_CUSTOMERS = VIEW_COMPANIES


@dataclass(frozen=True)
class CapabilityDefinition:
    capability: Capability
    name: str
    description: str
    category: str
    configurable: bool = True


CAPABILITY_CATALOG = (
    CapabilityDefinition(
        Capability.ACCESS_DASHBOARD,
        "Acessar painel operacional",
        "Visualizar indicadores operacionais.",
        "Painel",
    ),
    CapabilityDefinition(
        Capability.VIEW_ORDERS,
        "Visualizar pedidos",
        "Consultar pedidos e seus detalhes.",
        "Pedidos",
    ),
    CapabilityDefinition(
        Capability.CREATE_ORDERS, "Criar pedidos", "Cadastrar novos pedidos.", "Pedidos"
    ),
    CapabilityDefinition(
        Capability.EDIT_ORDERS,
        "Editar estrutura de pedido",
        "Alterar itens e dados estruturais.",
        "Pedidos",
    ),
    CapabilityDefinition(
        Capability.CHANGE_ORDER_STATUS,
        "Alterar status",
        "Executar transições operacionais.",
        "Pedidos",
    ),
    CapabilityDefinition(
        Capability.CANCEL_ORDERS,
        "Cancelar pedido",
        "Cancelar pedidos sem exclusão física.",
        "Pedidos",
    ),
    CapabilityDefinition(
        Capability.VIEW_REQUESTS,
        "Visualizar solicitações",
        "Consultar solicitações B2B.",
        "Solicitações",
    ),
    CapabilityDefinition(
        Capability.APPROVE_REQUESTS,
        "Aprovar solicitações",
        "Aprovar solicitações B2B.",
        "Solicitações",
    ),
    CapabilityDefinition(
        Capability.REJECT_REQUESTS,
        "Rejeitar solicitações",
        "Rejeitar solicitações B2B.",
        "Solicitações",
    ),
    CapabilityDefinition(
        Capability.REQUEST_CORRECTION,
        "Solicitar correção",
        "Devolver uma solicitação para correção.",
        "Solicitações",
    ),
    CapabilityDefinition(
        Capability.VIEW_COMPANIES,
        "Visualizar empresas",
        "Consultar empresas.",
        "Empresas e produtos",
    ),
    CapabilityDefinition(
        Capability.MANAGE_COMPANIES,
        "Gerenciar empresas",
        "Cadastrar e alterar empresas.",
        "Empresas e produtos",
    ),
    CapabilityDefinition(
        Capability.VIEW_PRODUCTS,
        "Visualizar produtos",
        "Consultar produtos.",
        "Empresas e produtos",
    ),
    CapabilityDefinition(
        Capability.MANAGE_PRODUCTS,
        "Gerenciar produtos",
        "Cadastrar e alterar produtos.",
        "Empresas e produtos",
    ),
    CapabilityDefinition(
        Capability.VIEW_CLOSINGS,
        "Visualizar fechamentos",
        "Consultar fechamentos financeiros.",
        "Financeiro",
    ),
    CapabilityDefinition(
        Capability.REVIEW_CLOSINGS,
        "Conferir fechamentos",
        "Gerar, recalcular e atualizar fechamentos.",
        "Financeiro",
    ),
    CapabilityDefinition(
        Capability.EXPORT_CLOSINGS,
        "Exportar fechamento",
        "Exportar fechamento em CSV.",
        "Financeiro",
    ),
    CapabilityDefinition(
        Capability.VIEW_REPORTS,
        "Visualizar relatórios",
        "Consultar relatórios financeiros.",
        "Financeiro",
    ),
    CapabilityDefinition(
        Capability.VIEW_AUDIT,
        "Visualizar auditoria",
        "Consultar eventos de auditoria.",
        "Financeiro",
    ),
    CapabilityDefinition(
        Capability.ACCESS_INTELLIGENCE,
        "Acessar Central Inteligente",
        "Consultar recomendações operacionais.",
        "Central Inteligente",
    ),
    CapabilityDefinition(
        Capability.RECORD_AI_FEEDBACK,
        "Registrar feedback permitido",
        "Avaliar recomendações visíveis.",
        "Central Inteligente",
    ),
    CapabilityDefinition(
        Capability.MANAGE_ATTENDANTS,
        "Gerenciar Atendentes",
        "Criar e administrar Atendentes.",
        "Usuários e acessos",
    ),
    CapabilityDefinition(
        Capability.MANAGE_LOWER_USERS,
        "Gerenciar perfis inferiores",
        "Administrar usuários abaixo do próprio perfil.",
        "Usuários e acessos",
    ),
    CapabilityDefinition(
        Capability.ACCESS_TECHNICAL_AREA,
        "Acessar área técnica sanitizada",
        "Acessar suporte sem infraestrutura ou segredos.",
        "Suporte técnico",
    ),
    CapabilityDefinition(
        Capability.MANAGE_SYSTEM_ADMINS,
        "Administrar outro Administrador do Sistema",
        "Protegida: exclusiva da conta raiz.",
        "Usuários e acessos",
        False,
    ),
    CapabilityDefinition(
        Capability.VIEW_ALL_USERS,
        "Visualizar todos os usuários internos",
        "Protegida pela hierarquia de gestão.",
        "Usuários e acessos",
        False,
    ),
    CapabilityDefinition(
        Capability.ACCESS_ADMIN_SETTINGS,
        "Acessar configurações administrativas",
        "Protegida pelo sistema.",
        "Usuários e acessos",
        False,
    ),
    CapabilityDefinition(
        Capability.ACCESS_ALL_OPERATIONS,
        "Acesso operacional irrestrito",
        "Protegida: não configurável individualmente.",
        "Suporte técnico",
        False,
    ),
)
CONFIGURABLE_CAPABILITIES = frozenset(
    item.capability for item in CAPABILITY_CATALOG if item.configurable
)

DIRECTOR_CAPABILITIES = frozenset(
    {
        Capability.ACCESS_DASHBOARD,
        Capability.VIEW_ORDERS,
        Capability.CREATE_ORDERS,
        Capability.EDIT_ORDERS,
        Capability.CHANGE_ORDER_STATUS,
        Capability.CANCEL_ORDERS,
        Capability.VIEW_REQUESTS,
        Capability.APPROVE_REQUESTS,
        Capability.REJECT_REQUESTS,
        Capability.REQUEST_CORRECTION,
        Capability.VIEW_COMPANIES,
        Capability.MANAGE_COMPANIES,
        Capability.VIEW_PRODUCTS,
        Capability.MANAGE_PRODUCTS,
        Capability.VIEW_CLOSINGS,
        Capability.REVIEW_CLOSINGS,
        Capability.EXPORT_CLOSINGS,
        Capability.VIEW_REPORTS,
        Capability.VIEW_AUDIT,
        Capability.ACCESS_INTELLIGENCE,
        Capability.RECORD_AI_FEEDBACK,
        Capability.MANAGE_ATTENDANTS,
    }
)
SYSTEM_ADMIN_CAPABILITIES = frozenset(Capability) - {Capability.MANAGE_SYSTEM_ADMINS}
ATTENDANT_CAPABILITIES = frozenset(
    {
        Capability.ACCESS_DASHBOARD,
        Capability.VIEW_ORDERS,
        Capability.CREATE_ORDERS,
        Capability.CHANGE_ORDER_STATUS,
        Capability.CANCEL_ORDERS,
        Capability.VIEW_REQUESTS,
        Capability.APPROVE_REQUESTS,
        Capability.REQUEST_CORRECTION,
        Capability.VIEW_COMPANIES,
        Capability.MANAGE_COMPANIES,
        Capability.VIEW_PRODUCTS,
        Capability.MANAGE_PRODUCTS,
        Capability.ACCESS_INTELLIGENCE,
        Capability.RECORD_AI_FEEDBACK,
    }
)
ROLE_CAPABILITIES = {
    ROLE_SYSTEM_ADMIN: SYSTEM_ADMIN_CAPABILITIES,
    ROLE_ADMIN: DIRECTOR_CAPABILITIES,
    ROLE_ATTENDANCE: ATTENDANT_CAPABILITIES,
    ROLE_PRODUCTION: frozenset(
        {
            Capability.ACCESS_DASHBOARD,
            Capability.VIEW_ORDERS,
            Capability.CHANGE_ORDER_STATUS,
            Capability.ACCESS_INTELLIGENCE,
            Capability.RECORD_AI_FEEDBACK,
        }
    ),
    ROLE_EXPEDITION: frozenset(
        {
            Capability.ACCESS_DASHBOARD,
            Capability.VIEW_ORDERS,
            Capability.CHANGE_ORDER_STATUS,
            Capability.ACCESS_INTELLIGENCE,
            Capability.RECORD_AI_FEEDBACK,
        }
    ),
    ROLE_FINANCE: frozenset(
        {
            Capability.ACCESS_DASHBOARD,
            Capability.VIEW_ORDERS,
            Capability.VIEW_CLOSINGS,
            Capability.REVIEW_CLOSINGS,
            Capability.EXPORT_CLOSINGS,
            Capability.VIEW_REPORTS,
            Capability.VIEW_AUDIT,
            Capability.ACCESS_INTELLIGENCE,
            Capability.RECORD_AI_FEEDBACK,
        }
    ),
    ROLE_SUPPORT: frozenset({Capability.ACCESS_TECHNICAL_AREA}),
}

COMPATIBILITY_PERMISSIONS = {
    Capability.ACCESS_DASHBOARD: frozenset(
        {"orders.view_order", "customer_portal.review_customerorderrequest"}
    ),
    Capability.VIEW_ORDERS: frozenset(
        {"orders.view_order", "customer_portal.review_customerorderrequest"}
    ),
    Capability.VIEW_REQUESTS: frozenset({"customer_portal.review_customerorderrequest"}),
}


def is_root_system_admin(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "username", None) == ROOT_USERNAME
        and getattr(user, "is_superuser", False)
    )


def base_capabilities_for_user(user) -> frozenset[Capability]:
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return frozenset()
    role_names = user.groups.values_list("name", flat=True)
    return frozenset().union(*(ROLE_CAPABILITIES.get(role, ()) for role in role_names))


def capability_overrides_for_user(user) -> tuple[frozenset[Capability], frozenset[Capability]]:
    cached = getattr(user, "_capability_override_cache", None)
    if cached is None:
        rows = user.capability_overrides.values_list("capability", "effect")
        allowed = frozenset(Capability(value) for value, effect in rows if effect == "allow")
        denied = frozenset(Capability(value) for value, effect in rows if effect == "deny")
        cached = (allowed, denied)
        user._capability_override_cache = cached
    return cached


def effective_capabilities_for_user(user) -> frozenset[Capability]:
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return frozenset()
    if is_root_system_admin(user):
        return frozenset(Capability)
    capabilities = set(base_capabilities_for_user(user))
    for capability, permissions in COMPATIBILITY_PERMISSIONS.items():
        if any(user.has_perm(permission) for permission in permissions):
            capabilities.add(capability)
    allowed, denied = capability_overrides_for_user(user)
    capabilities.update(allowed)
    capabilities.difference_update(denied)
    return frozenset(capabilities)


def user_has_capability(user, capability: Capability | str) -> bool:
    try:
        normalized = Capability(capability)
    except ValueError:
        return False
    return normalized in effective_capabilities_for_user(user)


class CapabilityRequiredMixin(LoginRequiredMixin):
    capability_required: Capability

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not user_has_capability(request.user, self.capability_required):
            raise PermissionDenied("Seu perfil não permite acessar este recurso.")
        return super().dispatch(request, *args, **kwargs)
