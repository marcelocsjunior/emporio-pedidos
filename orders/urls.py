from django.urls import path

from .assistant_views import OperationalDashboardView
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
    CompanyListView,
    CompanyToggleActiveView,
    CompanyUpdateView,
    OrderCreateView,
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
    path("empresas/", CompanyListView.as_view(), name="company-list"),
    path("empresas/nova/", CompanyCreateView.as_view(), name="company-create"),
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
    path("pedidos/novo/", OrderCreateView.as_view(), name="order-create"),
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
