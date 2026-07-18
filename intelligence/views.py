from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView
from orders.services import record_audit

from .access import user_can_process_ai, visible_recommendations_for_user
from .engine import audit_manual_enqueue, enqueue_due_events
from .models import AIFeedback, AIRecommendation, DataContext


class CentralIntelligenceView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "intelligence.view_airecommendation"
    raise_exception = True
    model = AIRecommendation
    template_name = "intelligence/central.html"
    context_object_name = "recommendations"
    paginate_by = 30

    def get_queryset(self):
        queryset = visible_recommendations_for_user(self.request.user)
        category = self.request.GET.get("category", "").strip()
        status = self.request.GET.get("status", "").strip()
        data_context = self.request.GET.get("context", "").strip()
        if category in AIRecommendation.Category.values:
            queryset = queryset.filter(category=category)
        if status in AIRecommendation.Status.values:
            queryset = queryset.filter(status=status)
        if data_context in DataContext.values:
            queryset = queryset.filter(data_context=data_context)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        visible = visible_recommendations_for_user(self.request.user)
        context.update(
            {
                "ai_mode": settings.AI_MODE,
                "ai_enabled": settings.AI_ENABLED,
                "provider_configured": bool(settings.GEMINI_API_KEY),
                "can_process": user_can_process_ai(self.request.user),
                "category_choices": AIRecommendation.Category.choices,
                "status_choices": AIRecommendation.Status.choices,
                "context_choices": DataContext.choices,
                "new_count": visible.filter(status=AIRecommendation.Status.NEW).count(),
                "critical_count": visible.filter(
                    severity=AIRecommendation.Severity.CRITICAL,
                    status__in=(AIRecommendation.Status.NEW, AIRecommendation.Status.VIEWED),
                ).count(),
            }
        )
        return context


class RecommendationFeedbackView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "intelligence.add_aifeedback"
    raise_exception = True
    http_method_names = ("post",)

    @transaction.atomic
    def post(self, request: HttpRequest, pk) -> HttpResponse:
        recommendation = get_object_or_404(
            visible_recommendations_for_user(request.user).select_for_update(),
            pk=pk,
        )
        rating = request.POST.get("rating", "").strip()
        if rating not in AIFeedback.Rating.values:
            messages.error(request, "Avaliação inválida.")
            return redirect("intelligence:central")
        notes = request.POST.get("notes", "").strip()[:255]
        feedback, created = AIFeedback.objects.update_or_create(
            recommendation=recommendation,
            user=request.user,
            defaults={"rating": rating, "notes": notes},
        )
        recommendation.status = {
            AIFeedback.Rating.USEFUL: AIRecommendation.Status.USEFUL,
            AIFeedback.Rating.INCORRECT: AIRecommendation.Status.INCORRECT,
            AIFeedback.Rating.NOT_APPLICABLE: AIRecommendation.Status.NOT_APPLICABLE,
        }[rating]
        recommendation.save(update_fields=("status", "updated_at"))
        record_audit(
            actor=request.user,
            action="intelligence.feedback_created" if created else "intelligence.feedback_updated",
            entity=feedback,
            payload={
                "recommendation_id": str(recommendation.pk),
                "rating": rating,
            },
        )
        messages.success(request, "Avaliação registrada.")
        return redirect("intelligence:central")


class ManualIntelligenceEnqueueView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "intelligence.process_ai_events"
    raise_exception = True
    http_method_names = ("post",)

    def post(self, request: HttpRequest) -> HttpResponse:
        created = enqueue_due_events()
        audit_manual_enqueue(actor=request.user, created=created)
        total = sum(created.values())
        messages.success(
            request,
            f"Varredura concluída: {total} evento(s) novo(s) enfileirado(s).",
        )
        return redirect("intelligence:central")
