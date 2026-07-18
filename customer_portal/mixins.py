from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied

from .models import CustomerPortalAccess


class CustomerPortalAccessMixin(LoginRequiredMixin):
    portal_access: CustomerPortalAccess

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)

        try:
            access = CustomerPortalAccess.objects.select_related("company").get(
                user=request.user,
                active=True,
                company__active=True,
            )
        except CustomerPortalAccess.DoesNotExist as exc:
            raise PermissionDenied("Acesso ao portal não autorizado.") from exc

        self.portal_access = access
        return super().dispatch(request, *args, **kwargs)


class ReviewPermissionMixin(LoginRequiredMixin, PermissionRequiredMixin):
    permission_required = "customer_portal.review_customerorderrequest"
    raise_exception = True
