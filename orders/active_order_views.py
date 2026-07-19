from __future__ import annotations

from django.http import HttpRequest, HttpResponse

from intelligence.active_assistant import notify_order_created

from .models import Order
from .views import OrderCreateView


class ActiveOrderCreateView(OrderCreateView):
    """Preserva o fluxo validado e notifica somente após a criação oficial."""

    def post(self, request: HttpRequest) -> HttpResponse:
        creation_key = request.POST.get("creation_key", "").strip()
        existed_before = bool(
            creation_key and Order.objects.filter(creation_key=creation_key).exists()
        )
        response = super().post(request)
        if creation_key and not existed_before:
            order = Order.objects.filter(creation_key=creation_key).first()
            if order is not None:
                notify_order_created(order)
        return response
