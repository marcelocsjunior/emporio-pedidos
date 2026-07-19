from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie

from customer_portal.models import CustomerOrderRequest
from intelligence.active_assistant import (
    CATEGORY_NEW_ORDER,
    SOURCE_TYPE_ORDER,
    build_active_notification_panel,
    suppress_duplicate_order_cards,
)
from intelligence.models import AIRecommendation
from intelligence.operational_assistant import build_operational_assistant
from intelligence.request_alerts import (
    CATEGORY_NEW_REQUEST,
    SOURCE_TYPE_CUSTOMER_REQUEST,
    build_request_notification_panel,
)

from .models import Order
from .services import record_audit
from .views import DashboardView

logger = logging.getLogger("emporio.ai")

ORDER_ALERT_PERMISSION = "orders.view_order"
REQUEST_ALERT_PERMISSION = "customer_portal.review_customerorderrequest"


def _active_feature_enabled() -> bool:
    return bool(
        settings.AI_ASSISTANT_PANEL_ENABLED
        and settings.AI_ACTIVE_ASSISTANT_ENABLED
    )


def _can_view_active_alerts(user) -> bool:
    return bool(
        user.is_authenticated
        and (
            user.has_perm(ORDER_ALERT_PERMISSION)
            or user.has_perm(REQUEST_ALERT_PERMISSION)
        )
    )


def _assistant_context(request: HttpRequest) -> dict:
    enabled = bool(settings.AI_ASSISTANT_PANEL_ENABLED)
    feature_enabled = _active_feature_enabled()
    order_active_enabled = bool(
        feature_enabled and request.user.has_perm(ORDER_ALERT_PERMISSION)
    )
    request_active_enabled = bool(
        feature_enabled and request.user.has_perm(REQUEST_ALERT_PERMISSION)
    )
    active_enabled = order_active_enabled or request_active_enabled
    context = {
        "assistant_panel_enabled": enabled,
        "assistant_active_enabled": active_enabled,
        "assistant_order_active_enabled": order_active_enabled,
        "assistant_request_active_enabled": request_active_enabled,
        "assistant_panel": None,
        "active_notification_panel": None,
        "request_notification_panel": None,
        "assistant_panel_error": False,
        "assistant_active_error": False,
        "assistant_request_error": False,
        "assistant_total_open": 0,
        "assistant_refresh_url": "",
        "assistant_refresh_seconds": settings.AI_ACTIVE_ASSISTANT_POLL_SECONDS,
    }
    if not enabled:
        return context

    active_panel = None
    if order_active_enabled:
        try:
            active_panel = build_active_notification_panel(request.user)
            context["active_notification_panel"] = active_panel
        except Exception:
            logger.exception(
                "active_assistant_panel_failed request_id=%s user_id=%s",
                getattr(request, "request_id", "unavailable"),
                getattr(request.user, "pk", "unavailable"),
            )
            context["assistant_active_error"] = True

    request_panel = None
    if request_active_enabled:
        try:
            request_panel = build_request_notification_panel(request.user)
            context["request_notification_panel"] = request_panel
        except Exception:
            logger.exception(
                "request_alert_panel_failed request_id=%s user_id=%s",
                getattr(request, "request_id", "unavailable"),
                getattr(request.user, "pk", "unavailable"),
            )
            context["assistant_request_error"] = True

    if active_enabled:
        context["assistant_refresh_url"] = reverse("assistant-updates")

    try:
        panel = build_operational_assistant(request.user)
        if active_panel is not None:
            panel = suppress_duplicate_order_cards(panel, active_panel.source_keys)
        context["assistant_panel"] = panel
    except Exception:
        logger.exception(
            "assistant_panel_failed request_id=%s user_id=%s",
            getattr(request, "request_id", "unavailable"),
            getattr(request.user, "pk", "unavailable"),
        )
        context["assistant_panel_error"] = True

    order_count = active_panel.new_count if active_panel is not None else 0
    request_count = request_panel.new_count if request_panel is not None else 0
    panel_count = context["assistant_panel"].total_open if context["assistant_panel"] else 0
    context["assistant_total_open"] = order_count + request_count + panel_count
    return context


@method_decorator(ensure_csrf_cookie, name="dispatch")
class OperationalDashboardView(DashboardView):
    """Acrescenta prioridades assistidas sem alterar o fluxo operacional existente."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_assistant_context(self.request))
        return context


class OperationalAssistantUpdatesView(LoginRequiredMixin, View):
    http_method_names = ("get",)

    def get(self, request: HttpRequest) -> HttpResponse:
        if not _active_feature_enabled():
            raise Http404
        if not _can_view_active_alerts(request.user):
            raise PermissionDenied
        return render(
            request,
            "orders/_operational_assistant.html",
            _assistant_context(request),
        )


class RecommendationViewedView(LoginRequiredMixin, View):
    http_method_names = ("post",)

    @transaction.atomic
    def post(self, request: HttpRequest, pk) -> HttpResponse:
        recommendation = get_object_or_404(
            AIRecommendation.objects.select_for_update(),
            pk=pk,
        )

        if (
            recommendation.category == CATEGORY_NEW_ORDER
            and recommendation.source_type == SOURCE_TYPE_ORDER
        ):
            if not request.user.has_perm(ORDER_ALERT_PERMISSION):
                raise PermissionDenied
            order = get_object_or_404(Order, pk=recommendation.source_id)
            audit_action = "assistant.notification_viewed"
            audit_payload = {
                "order_id": str(order.pk),
                "order_number": order.number,
            }
        elif (
            recommendation.category == CATEGORY_NEW_REQUEST
            and recommendation.source_type == SOURCE_TYPE_CUSTOMER_REQUEST
        ):
            if not request.user.has_perm(REQUEST_ALERT_PERMISSION):
                raise PermissionDenied
            customer_request = get_object_or_404(
                CustomerOrderRequest,
                pk=recommendation.source_id,
            )
            audit_action = "assistant.request_notification_viewed"
            audit_payload = {
                "request_id": str(customer_request.pk),
                "request_protocol": customer_request.protocol,
            }
        else:
            raise Http404

        if recommendation.status == AIRecommendation.Status.NEW:
            recommendation.status = AIRecommendation.Status.VIEWED
            recommendation.save(update_fields=("status", "updated_at"))
            record_audit(
                actor=request.user,
                action=audit_action,
                entity=recommendation,
                payload=audit_payload,
            )
        return redirect("dashboard")
