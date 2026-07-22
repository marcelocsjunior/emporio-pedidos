from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache

from accounts.access import Capability, effective_capabilities_for_user
from accounts.roles import ROLE_ADMIN, ROLE_ATTENDANCE, ROLE_MANAGEMENT
from customer_portal.models import CustomerOrderRequest

from .models import Order

EVENT_LIMIT = 30
NEW_EVENT_WINDOW = timedelta(hours=24)
ATTENDANCE_ROLES = frozenset({ROLE_ADMIN, ROLE_MANAGEMENT, ROLE_ATTENDANCE})


def _notification_audience(user) -> tuple[bool, bool]:
    """Return (new requests, operational orders/delays) from effective access."""
    roles = set(user.groups.values_list("name", flat=True))
    capabilities = effective_capabilities_for_user(user)
    attendance_role = bool(roles & ATTENDANCE_ROLES)
    operational_equivalent = all(
        capability in capabilities
        for capability in (
            Capability.VIEW_ORDERS,
            Capability.CREATE_ORDERS,
            Capability.CHANGE_ORDER_STATUS,
            Capability.VIEW_REQUESTS,
        )
    )
    order_alerts = attendance_role or operational_equivalent
    request_alerts = order_alerts or Capability.APPROVE_REQUESTS in capabilities
    return request_alerts, order_alerts


def _event(kind: str, object_id, timestamp, label: str, url: str) -> dict[str, str]:
    stamp = timestamp.isoformat()
    return {
        "id": f"{kind}:{object_id}:{stamp}",
        "type": kind,
        "label": label,
        "occurred_at": stamp,
        "url": url,
    }


@method_decorator(never_cache, name="dispatch")
class AttendanceNotificationUpdatesView(View):
    http_method_names = ("get",)

    def get(self, request):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())

        request_alerts, order_alerts = _notification_audience(request.user)
        if not request_alerts and not order_alerts:
            return JsonResponse({"detail": "Acesso negado."}, status=403)

        now = timezone.now()
        events: list[dict[str, str]] = []
        if request_alerts:
            requests = CustomerOrderRequest.objects.filter(
                status=CustomerOrderRequest.Status.SUBMITTED,
                submitted_at__gte=now - NEW_EVENT_WINDOW,
            ).values("id", "protocol", "submitted_at")[:EVENT_LIMIT]
            events.extend(
                _event(
                    "new_request",
                    item["id"],
                    item["submitted_at"],
                    f"Nova solicitação {item['protocol']}",
                    reverse("customer_portal:request-review", args=(item["id"],)),
                )
                for item in requests
            )

        if order_alerts:
            orders = Order.objects.filter(created_at__gte=now - NEW_EVENT_WINDOW).values(
                "id", "number", "created_at"
            )[:EVENT_LIMIT]
            events.extend(
                _event(
                    "new_order",
                    item["id"],
                    item["created_at"],
                    f"Novo pedido {item['number']}",
                    reverse("order-detail", args=(item["id"],)),
                )
                for item in orders
            )

            # Somente prazos completos e explícitos entram na regra de atraso.
            local_now = timezone.localtime(now)
            late_candidates = Order.objects.exclude(
                status__in=(Order.Status.DELIVERED, Order.Status.CANCELLED)
            ).filter(delivery_time__isnull=False).filter(
                Q(delivery_date__lt=local_now.date())
                | Q(delivery_date=local_now.date(), delivery_time__lt=local_now.time())
            ).values(
                "id", "number", "delivery_date", "delivery_time", "updated_at"
            )[:EVENT_LIMIT]
            for item in late_candidates:
                deadline = timezone.make_aware(
                    datetime.combine(item["delivery_date"], item["delivery_time"]),
                    timezone.get_current_timezone(),
                )
                if deadline < now:
                    events.append(
                        _event(
                            "late_order",
                            item["id"],
                            deadline,
                            f"Pedido atrasado {item['number']}",
                            reverse("order-detail", args=(item["id"],)),
                        )
                    )

        events.sort(key=lambda item: (item["occurred_at"], item["id"]), reverse=True)
        response = JsonResponse({"events": events[:EVENT_LIMIT], "limit": EVENT_LIMIT})
        response["Pragma"] = "no-cache"
        return response
