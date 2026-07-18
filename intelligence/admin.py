from django.contrib import admin

from .models import (
    AIAnalysisRun,
    AIEvent,
    AIFeedback,
    AIPromptVersion,
    AIRecommendation,
    AIUsage,
)


@admin.register(AIEvent)
class AIEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "data_context", "status", "attempts", "created_at")
    list_filter = ("event_type", "data_context", "status")
    search_fields = ("source_type", "source_id", "idempotency_key")
    readonly_fields = ("idempotency_key", "payload", "created_at", "updated_at")


@admin.register(AIRecommendation)
class AIRecommendationAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "severity", "data_context", "status", "created_at")
    list_filter = ("category", "severity", "data_context", "status")
    search_fields = ("title", "summary", "source_id")
    readonly_fields = ("idempotency_key", "evidence", "created_at", "updated_at")


admin.site.register(AIAnalysisRun)
admin.site.register(AIFeedback)
admin.site.register(AIPromptVersion)
admin.site.register(AIUsage)
