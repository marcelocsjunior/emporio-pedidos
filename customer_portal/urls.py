from django.urls import path

from .active_review_views import ActiveRequestApproveView
from .portal_views import (
    PortalRequestCancelView,
    PortalRequestCreateView,
    PortalRequestDetailView,
    PortalRequestListView,
    PortalRequestSubmitView,
    PortalRequestUpdateView,
)
from .review_views import (
    RequestCorrectionView,
    RequestQueueView,
    RequestRejectView,
    RequestReviewView,
    RequestStartReviewView,
)

app_name = "customer_portal"

urlpatterns = [
    path("portal/", PortalRequestListView.as_view(), name="request-list"),
    path("portal/nova/", PortalRequestCreateView.as_view(), name="request-create"),
    path("portal/<uuid:pk>/", PortalRequestDetailView.as_view(), name="request-detail"),
    path("portal/<uuid:pk>/editar/", PortalRequestUpdateView.as_view(), name="request-update"),
    path("portal/<uuid:pk>/enviar/", PortalRequestSubmitView.as_view(), name="request-submit"),
    path("portal/<uuid:pk>/cancelar/", PortalRequestCancelView.as_view(), name="request-cancel"),
    path("solicitacoes/", RequestQueueView.as_view(), name="request-queue"),
    path("solicitacoes/<uuid:pk>/", RequestReviewView.as_view(), name="request-review"),
    path(
        "solicitacoes/<uuid:pk>/iniciar-analise/",
        RequestStartReviewView.as_view(),
        name="request-start-review",
    ),
    path(
        "solicitacoes/<uuid:pk>/correcao/",
        RequestCorrectionView.as_view(),
        name="request-correction",
    ),
    path(
        "solicitacoes/<uuid:pk>/rejeitar/",
        RequestRejectView.as_view(),
        name="request-reject",
    ),
    path(
        "solicitacoes/<uuid:pk>/aprovar/",
        ActiveRequestApproveView.as_view(),
        name="request-approve",
    ),
]
