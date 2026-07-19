from __future__ import annotations

import logging

from django.conf import settings

from intelligence.operational_assistant import build_operational_assistant

from .views import DashboardView

logger = logging.getLogger("emporio.ai")


class OperationalDashboardView(DashboardView):
    """Acrescenta prioridades assistidas sem alterar o fluxo operacional existente."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        enabled = bool(settings.AI_ASSISTANT_PANEL_ENABLED)
        context.update(
            {
                "assistant_panel_enabled": enabled,
                "assistant_panel": None,
                "assistant_panel_error": False,
            }
        )
        if not enabled:
            return context

        try:
            context["assistant_panel"] = build_operational_assistant(self.request.user)
        except Exception:
            logger.exception(
                "assistant_panel_failed request_id=%s user_id=%s",
                getattr(self.request, "request_id", "unavailable"),
                getattr(self.request.user, "pk", "unavailable"),
            )
            context["assistant_panel_error"] = True
        return context
