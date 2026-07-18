from __future__ import annotations

from django.conf import settings
from django.db.models import Q, QuerySet

from .models import AIRecommendation

CATEGORY_PERMISSIONS = {
    AIRecommendation.Category.DELAY: "intelligence.view_ai_delay",
    AIRecommendation.Category.DUPLICATE: "intelligence.view_ai_duplicate",
    AIRecommendation.Category.PRODUCTION: "intelligence.view_ai_production",
    AIRecommendation.Category.CLOSING: "intelligence.view_ai_finance",
}


def user_can_process_ai(user) -> bool:
    return bool(user.is_superuser or user.has_perm("intelligence.process_ai_events"))


def visible_recommendations_for_user(user) -> QuerySet[AIRecommendation]:
    queryset = AIRecommendation.objects.select_related("event")
    if not user.is_authenticated or not user.has_perm("intelligence.view_airecommendation"):
        return queryset.none()

    if settings.AI_MODE == "shadow" and not user_can_process_ai(user):
        return queryset.none()

    if user_can_process_ai(user):
        return queryset

    categories = [
        category
        for category, permission in CATEGORY_PERMISSIONS.items()
        if user.has_perm(permission)
    ]
    if not categories:
        return queryset.none()
    return queryset.filter(Q(category__in=categories))
