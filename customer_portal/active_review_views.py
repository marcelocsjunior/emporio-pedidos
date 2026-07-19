from __future__ import annotations

from django.http import HttpRequest, HttpResponse

from intelligence.active_assistant import notify_order_created

from .models import CustomerOrderRequest
from .review_views import RequestApproveView


class ActiveRequestApproveView(RequestApproveView):
    """Notifica somente depois de a conversão transacional ter sido concluída."""

    def post(self, request: HttpRequest, pk) -> HttpResponse:
        converted_before = (
            CustomerOrderRequest.objects.filter(pk=pk)
            .values_list("converted_order_id", flat=True)
            .first()
        )
        response = super().post(request, pk)
        customer_request = (
            CustomerOrderRequest.objects.filter(pk=pk)
            .select_related("converted_order")
            .first()
        )
        if (
            customer_request is not None
            and customer_request.converted_order_id
            and converted_before is None
        ):
            notify_order_created(customer_request.converted_order)
        return response
