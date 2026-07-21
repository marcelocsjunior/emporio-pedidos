from django.urls import path

from .active_order_views import ActiveOrderCreateView
from .assistant_views import (
    OperationalAssistantUpdatesView,
    OperationalDashboardView,
    RecommendationViewedView,
)
from .closing_views import (
    ClosingCsvExportView,
    ClosingDetailView,
    ClosingGenerateView,
    ClosingListView,
    ClosingNotesUpdateView,
    ClosingRecalculateView,
    ClosingStatusUpdateView,
)
from .views import (
    AuditListView,
    CompanyCreateView,
    CompanyImportDetailView,
    CompanyImportListView,
    CompanyImportMappingView,
    CompanyImportPreviewView,
    CompanyImportRollbackView,
    CompanyImportUploadView,
    CompanyListView,
    CompanyToggleActiveView,
    CompanyUpdateView,
    OrderDetailView,
    OrderListView,
    OrderStatusUpdateView,
    OrderUpdateView,
    ProductCreateView,
    ProductListView,
    ProductToggleActiveView,
    ProductUpdateView,
)

urlpatterns = [
    path("", OperationalDashboardView.as_view(), name="dashboard"),
    path(
        "assistente-operacional/atualizacoes/",
        OperationalAssistantUpdatesView.as_view(),
        name="assistant-updates",
    ),
    path(
        "assistente-operacional/recomendacoes/<uuid:pk>/visualizar/",
        RecommendationViewedView.as_view(),
        name="assistant-recommendation-viewed",
    ),
    path("empresas/", CompanyListView.as_view(), name="company-list"),
    path("empresas/nova/", CompanyCreateView.as_view(), name="company-create"),
    path("empresas/importacoes/", CompanyImportListView.as_view(), name="company-import-list"),
    path(
        "empresas/importacoes/nova/",
        CompanyImportUploadView.as_view(),
        name="company-import-upload",
    ),
    path(
        "empresas/importacoes/<uuid:pk>/mapear/",
        CompanyImportMappingView.as_view(),
        name="company-import-map",
    ),
    path(
        "empresas/importacoes/<uuid:pk>/previsualizar/",
        CompanyImportPreviewView.as_view(),
        name="company-import-preview",
    ),
    path(
        "empresas/importacoes/<uuid:pk>/",
        CompanyImportDetailView.as_view(),
        name="company-import-detail",
    ),
    path(
        "empresas/importacoes/<uuid:pk>/rollback/",
        CompanyImportRollbackView.as_view(),
        name="company-import-rollback",
    ),
    path("empresas/<uuid:pk>/editar/", CompanyUpdateView.as_view(), name="company-update"),
    path(
        "empresas/<uuid:pk>/situacao/",
        CompanyToggleActiveView.as_view(),
        name="company-toggle-active",
    ),
    path("produtos/", ProductListView.as_view(), name="product-list"),
    path("produtos/novo/", ProductCreateView.as_view(), name="product-create"),
    path("produtos/<uuid:pk>/editar/", ProductUpdateView.as_view(), name="product-update"),
    path(
        "produtos/<uuid:pk>/situacao/",
        ProductToggleActiveView.as_view(),
        name="product-toggle-active",
    ),
    path("pedidos/", OrderListView.as_view(), name="order-list"),
    path("pedidos/novo/", ActiveOrderCreateView.as_view(), name="order-create"),
    path("pedidos/<uuid:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path("pedidos/<uuid:pk>/editar/", OrderUpdateView.as_view(), name="order-update"),
    path(
        "pedidos/<uuid:pk>/status/",
        OrderStatusUpdateView.as_view(),
        name="order-status-update",
    ),
    path("fechamentos/", ClosingListView.as_view(), name="closing-list"),
    path("fechamentos/gerar/", ClosingGenerateView.as_view(), name="closing-generate"),
    path("fechamentos/<uuid:pk>/", ClosingDetailView.as_view(), name="closing-detail"),
    path(
        "fechamentos/<uuid:pk>/recalcular/",
        ClosingRecalculateView.as_view(),
        name="closing-recalculate",
    ),
    path(
        "fechamentos/<uuid:pk>/status/",
        ClosingStatusUpdateView.as_view(),
        name="closing-status-update",
    ),
    path(
        "fechamentos/<uuid:pk>/observacoes/",
        ClosingNotesUpdateView.as_view(),
        name="closing-notes-update",
    ),
    path(
        "fechamentos/<uuid:pk>/exportar.csv",
        ClosingCsvExportView.as_view(),
        name="closing-export-csv",
    ),
    path("auditoria/", AuditListView.as_view(), name="audit-list"),
]
