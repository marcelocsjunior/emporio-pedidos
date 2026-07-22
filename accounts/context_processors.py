def user_roles(request):
    if not request.user.is_authenticated:
        return {"current_roles": ()}
    from .access import Capability, is_root_system_admin, user_has_capability
    from .roles import (
        ROLE_ADMIN,
        ROLE_ATTENDANCE,
        ROLE_MANAGEMENT,
        ROLE_SUPPORT,
        ROLE_SYSTEM_ADMIN,
    )

    role_names = tuple(request.user.groups.order_by("name").values_list("name", flat=True))
    visible_names = {
        ROLE_ADMIN: "Proprietária / Diretora",
        ROLE_ATTENDANCE: "Atendente",
        ROLE_SUPPORT: ROLE_SUPPORT,
        ROLE_SYSTEM_ADMIN: ROLE_SYSTEM_ADMIN,
    }
    if is_root_system_admin(request.user):
        roles = ("Administrador Raiz do Sistema",)
    else:
        roles = tuple(visible_names.get(role, role) for role in role_names)
    capability_flags = {
        f"can_{capability.value}": user_has_capability(request.user, capability)
        for capability in Capability
    }
    attendance_roles = {ROLE_ADMIN, ROLE_MANAGEMENT, ROLE_ATTENDANCE}
    operational_equivalent = all(
        capability_flags[f"can_{capability.value}"]
        for capability in (
            Capability.VIEW_ORDERS,
            Capability.CREATE_ORDERS,
            Capability.CHANGE_ORDER_STATUS,
            Capability.VIEW_REQUESTS,
        )
    )
    can_receive_internal_notifications = (
        bool(set(role_names) & attendance_roles)
        or operational_equivalent
        or capability_flags["can_approve_requests"]
    )
    return {
        "current_roles": roles,
        "can_manage_attendants": user_has_capability(request.user, Capability.MANAGE_ATTENDANTS),
        "can_access_technical_area": user_has_capability(
            request.user, Capability.ACCESS_TECHNICAL_AREA
        ),
        "can_manage_users": user_has_capability(request.user, Capability.MANAGE_LOWER_USERS),
        "can_receive_internal_notifications": can_receive_internal_notifications,
        **capability_flags,
    }
