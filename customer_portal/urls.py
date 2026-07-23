from django.urls import path

from .access_views import (
    AccessRequestQueueView,
    AccessRequestReviewView,
    PortalAccessDetailView,
    PortalAccessListView,
    PortalAccessStatusView,
    PortalPasswordResetView,
    PortalUserCreateView,
    PortalUserLinkView,
)
from .active_review_views import ActiveRequestApproveView
from .active_submit_views import ActivePortalRequestSubmitView
from .portal_views import (
    PortalOrderDetailView,
    PortalOrderNotificationUpdatesView,
    PortalOrderNotificationViewedView,
    PortalRequestCancelView,
    PortalRequestCreateView,
    PortalRequestDetailView,
    PortalRequestListView,
    PortalRequestUpdateView,
)
from .public_access import public_access_request_gate
from .review_views import (
    RequestCorrectionView,
    RequestQueueView,
    RequestRejectView,
    RequestReviewView,
    RequestStartReviewView,
)

app_name = "customer_portal"

urlpatterns = [
    path(
        "portal/solicitar-acesso/",
        public_access_request_gate,
        name="access-request-public",
    ),
    path("empresas/acessos/", PortalAccessListView.as_view(), name="access-list"),
    path("empresas/acessos/novo/", PortalUserCreateView.as_view(), name="access-create"),
    path("empresas/acessos/vincular/", PortalUserLinkView.as_view(), name="access-link"),
    path("empresas/acessos/<uuid:pk>/", PortalAccessDetailView.as_view(), name="access-detail"),
    path(
        "empresas/acessos/<uuid:pk>/<str:action>/",
        PortalAccessStatusView.as_view(),
        name="access-status",
    ),
    path(
        "empresas/acessos/<uuid:pk>/senha/redefinir/",
        PortalPasswordResetView.as_view(),
        name="access-password-reset",
    ),
    path(
        "empresas/solicitacoes-acesso/",
        AccessRequestQueueView.as_view(),
        name="access-request-queue",
    ),
    path(
        "empresas/solicitacoes-acesso/<uuid:pk>/",
        AccessRequestReviewView.as_view(),
        name="access-request-review",
    ),
    path("portal/", PortalRequestListView.as_view(), name="request-list"),
    path("portal/pedidos/<uuid:pk>/", PortalOrderDetailView.as_view(), name="order-detail"),
    path(
        "portal/atualizacoes-pedidos/",
        PortalOrderNotificationUpdatesView.as_view(),
        name="order-notification-updates",
    ),
    path(
        "portal/atualizacoes-pedidos/<uuid:pk>/visualizar/",
        PortalOrderNotificationViewedView.as_view(),
        name="order-notification-viewed",
    ),
    path("portal/nova/", PortalRequestCreateView.as_view(), name="request-create"),
    path("portal/<uuid:pk>/", PortalRequestDetailView.as_view(), name="request-detail"),
    path("portal/<uuid:pk>/editar/", PortalRequestUpdateView.as_view(), name="request-update"),
    path(
        "portal/<uuid:pk>/enviar/",
        ActivePortalRequestSubmitView.as_view(),
        name="request-submit",
    ),
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
