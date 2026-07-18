from django.contrib import admin
from django.http import JsonResponse
from django.urls import path


def healthcheck(request):
    return JsonResponse({"status": "ok", "service": "emporio-pedidos"})


urlpatterns = [
    path("health/", healthcheck, name="healthcheck"),
    path("admin/", admin.site.urls),
]
