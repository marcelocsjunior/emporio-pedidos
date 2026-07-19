from __future__ import annotations

from intelligence.request_alerts import notify_request_submitted

from .models import CustomerOrderRequest
from .portal_views import PortalRequestSubmitView


class ActivePortalRequestSubmitView(PortalRequestSubmitView):
    """Preserva a submissão oficial e cria o alerta operacional idempotente."""

    def post(self, request, pk):
        response = super().post(request, pk)
        customer_request = (
            CustomerOrderRequest.objects.select_related("company", "delivery_location")
            .filter(pk=pk)
            .first()
        )
        if customer_request is not None:
            notify_request_submitted(customer_request)
        return response
