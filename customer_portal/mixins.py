from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from accounts.access import Capability, CapabilityRequiredMixin

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


class ReviewPermissionMixin(CapabilityRequiredMixin):
    capability_required = Capability.VIEW_REQUESTS
