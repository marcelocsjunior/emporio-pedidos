from django.urls import path

from .views import (
    AuditListView,
    ClosingListView,
    CompanyListView,
    DashboardView,
    OrderDetailView,
    OrderListView,
    OrderStatusUpdateView,
    ProductListView,
)

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("empresas/", CompanyListView.as_view(), name="company-list"),
    path("produtos/", ProductListView.as_view(), name="product-list"),
    path("pedidos/", OrderListView.as_view(), name="order-list"),
    path("pedidos/<uuid:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path(
        "pedidos/<uuid:pk>/status/",
        OrderStatusUpdateView.as_view(),
        name="order-status-update",
    ),
    path("fechamentos/", ClosingListView.as_view(), name="closing-list"),
    path("auditoria/", AuditListView.as_view(), name="audit-list"),
]
