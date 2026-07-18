def user_roles(request):
    if not request.user.is_authenticated:
        return {"current_roles": ()}
    return {
        "current_roles": tuple(request.user.groups.order_by("name").values_list("name", flat=True))
    }
