from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthcheck(request):
    return JsonResponse({"status": "ok", "service": "emporio-pedidos"})


handler500 = "config.error_views.server_error"

admin.site.site_header = "Empório Pedidos — Administração"
admin.site.site_title = "Empório Pedidos"
admin.site.index_title = "Administração técnica"

urlpatterns = [
    path("health/", healthcheck, name="healthcheck"),
    path("conta/", include("accounts.urls")),
    path("inteligencia/", include("intelligence.urls")),
    path("", include("customer_portal.urls")),
    path("", include("orders.urls")),
    path("admin/", admin.site.urls),
]
