from django.urls import path

from .views import (
    CentralIntelligenceView,
    ManualIntelligenceEnqueueView,
    RecommendationFeedbackView,
)

app_name = "intelligence"

urlpatterns = [
    path("", CentralIntelligenceView.as_view(), name="central"),
    path("processar/", ManualIntelligenceEnqueueView.as_view(), name="enqueue"),
    path(
        "recomendacoes/<uuid:pk>/avaliar/",
        RecommendationFeedbackView.as_view(),
        name="feedback",
    ),
]
