from django.shortcuts import redirect

from accounts.access import Capability, user_has_capability


class CustomerPortalBoundaryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            request.path == "/"
            and user.is_authenticated
            and not user_has_capability(user, Capability.VIEW_ORDERS)
        ):
            access = getattr(user, "customer_portal_access", None)
            if access and access.active and access.company.active:
                return redirect("customer_portal:request-list")
        return self.get_response(request)
