from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from intelligence.active_assistant import (
    CATEGORY_NEW_ORDER,
    SOURCE_TYPE_ORDER,
    build_active_notification_panel,
    suppress_duplicate_order_cards,
)
from intelligence.models import AIRecommendation
from intelligence.operational_assistant import build_operational_assistant

from .models import Order
from .services import record_audit
from .views import DashboardView

logger = logging.getLogger("emporio.ai")


def _assistant_context(request: HttpRequest) -> dict:
    enabled = bool(settings.AI_ASSISTANT_PANEL_ENABLED)
    active_enabled = bool(
        enabled
        and settings.AI_ACTIVE_ASSISTANT_ENABLED
        and request.user.has_perm("orders.view_order")
    )
    context = {
        "assistant_panel_enabled": enabled,
        "assistant_active_enabled": active_enabled,
        "assistant_panel": None,
        "active_notification_panel": None,
        "assistant_panel_error": False,
        "assistant_active_error": False,
        "assistant_total_open": 0,
        "assistant_refresh_url": "",
        "assistant_refresh_seconds": settings.AI_ACTIVE_ASSISTANT_POLL_SECONDS,
    }
    if not enabled:
        return context

    active_panel = None
    if active_enabled:
        try:
            active_panel = build_active_notification_panel(request.user)
            context["active_notification_panel"] = active_panel
            context["assistant_refresh_url"] = reverse("assistant-updates")
        except Exception:
            logger.exception(
                "active_assistant_panel_failed request_id=%s user_id=%s",
                getattr(request, "request_id", "unavailable"),
                getattr(request.user, "pk", "unavailable"),
            )
            context["assistant_active_error"] = True

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

    active_count = active_panel.new_count if active_panel is not None else 0
    panel_count = context["assistant_panel"].total_open if context["assistant_panel"] else 0
    context["assistant_total_open"] = active_count + panel_count
    return context


class OperationalDashboardView(DashboardView):
    """Acrescenta prioridades assistidas sem alterar o fluxo operacional existente."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_assistant_context(self.request))
        return context


class OperationalAssistantUpdatesView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    View,
):
    permission_required = "orders.view_order"
    raise_exception = True
    http_method_names = ("get",)

    def get(self, request: HttpRequest) -> HttpResponse:
        if not (
            settings.AI_ASSISTANT_PANEL_ENABLED
            and settings.AI_ACTIVE_ASSISTANT_ENABLED
        ):
            raise Http404
        return render(
            request,
            "orders/_operational_assistant.html",
            _assistant_context(request),
        )


class RecommendationViewedView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    View,
):
    permission_required = "orders.view_order"
    raise_exception = True
    http_method_names = ("post",)

    @transaction.atomic
    def post(self, request: HttpRequest, pk) -> HttpResponse:
        recommendation = get_object_or_404(
            AIRecommendation.objects.select_for_update(),
            pk=pk,
            category=CATEGORY_NEW_ORDER,
            source_type=SOURCE_TYPE_ORDER,
        )
        order = get_object_or_404(Order, pk=recommendation.source_id)
        if recommendation.status == AIRecommendation.Status.NEW:
            recommendation.status = AIRecommendation.Status.VIEWED
            recommendation.save(update_fields=("status", "updated_at"))
            record_audit(
                actor=request.user,
                action="assistant.notification_viewed",
                entity=recommendation,
                payload={
                    "order_id": str(order.pk),
                    "order_number": order.number,
                },
            )
        return redirect("dashboard")
