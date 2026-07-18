from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import EmporioLoginView, EmporioPasswordChangeDoneView, EmporioPasswordChangeView

urlpatterns = [
    path("entrar/", EmporioLoginView.as_view(), name="login"),
    path("sair/", LogoutView.as_view(next_page="login"), name="logout"),
    path("alterar-senha/", EmporioPasswordChangeView.as_view(), name="password_change"),
    path(
        "alterar-senha/concluido/",
        EmporioPasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
]
