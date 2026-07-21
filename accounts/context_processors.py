def user_roles(request):
    if not request.user.is_authenticated:
        return {"current_roles": ()}
    from .access import Capability, is_root_system_admin, user_has_capability
    from .roles import ROLE_ADMIN, ROLE_ATTENDANCE, ROLE_SUPPORT, ROLE_SYSTEM_ADMIN

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
    return {
        "current_roles": roles,
        "can_manage_attendants": user_has_capability(
            request.user, Capability.MANAGE_ATTENDANTS
        ),
        "can_access_technical_area": user_has_capability(
            request.user, Capability.ACCESS_TECHNICAL_AREA
        ),
        "can_manage_users": user_has_capability(
            request.user, Capability.MANAGE_LOWER_USERS
        ),
    }
