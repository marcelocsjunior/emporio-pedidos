from __future__ import annotations

from django.conf import settings
from django.db.models import Q, QuerySet

from accounts.access import Capability, user_has_capability

from .active_assistant import CATEGORY_NEW_ORDER
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
    if not user_has_capability(user, Capability.ACCESS_INTELLIGENCE):
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
    filters = Q(category__in=categories)
    if user.has_perm("orders.view_order"):
        filters |= Q(category=CATEGORY_NEW_ORDER)
    return queryset.filter(filters)
