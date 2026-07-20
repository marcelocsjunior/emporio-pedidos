from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import (
    AttendantCreateView,
    AttendantListView,
    AttendantRequirePasswordChangeView,
    AttendantToggleActiveView,
    AttendantUpdateView,
    EmporioLoginView,
    EmporioPasswordChangeDoneView,
    EmporioPasswordChangeView,
    TechnicalAreaView,
    UserAccessCreateView,
    UserAccessListView,
    UserAccessRequirePasswordChangeView,
    UserAccessToggleActiveView,
    UserAccessUpdateView,
)

urlpatterns = [
    path("entrar/", EmporioLoginView.as_view(), name="login"),
    path("sair/", LogoutView.as_view(next_page="login"), name="logout"),
    path("alterar-senha/", EmporioPasswordChangeView.as_view(), name="password_change"),
    path(
        "alterar-senha/concluido/",
        EmporioPasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
    path(
        "configuracoes/usuarios/",
        UserAccessListView.as_view(),
        name="user-access-list",
    ),
    path(
        "configuracoes/usuarios/novo/",
        UserAccessCreateView.as_view(),
        name="user-access-create",
    ),
    path(
        "configuracoes/usuarios/<int:pk>/editar/",
        UserAccessUpdateView.as_view(),
        name="user-access-update",
    ),
    path(
        "configuracoes/usuarios/<int:pk>/situacao/",
        UserAccessToggleActiveView.as_view(),
        name="user-access-toggle-active",
    ),
    path(
        "configuracoes/usuarios/<int:pk>/troca-senha/",
        UserAccessRequirePasswordChangeView.as_view(),
        name="user-access-require-password-change",
    ),
    path(
        "configuracoes/usuarios/atendentes/",
        AttendantListView.as_view(),
        name="attendant-list",
    ),
    path(
        "configuracoes/usuarios/atendentes/novo/",
        AttendantCreateView.as_view(),
        name="attendant-create",
    ),
    path(
        "configuracoes/usuarios/atendentes/<int:pk>/editar/",
        AttendantUpdateView.as_view(),
        name="attendant-update",
    ),
    path(
        "configuracoes/usuarios/atendentes/<int:pk>/situacao/",
        AttendantToggleActiveView.as_view(),
        name="attendant-toggle-active",
    ),
    path(
        "configuracoes/usuarios/atendentes/<int:pk>/troca-senha/",
        AttendantRequirePasswordChangeView.as_view(),
        name="attendant-require-password-change",
    ),
    path("area-tecnica/", TechnicalAreaView.as_view(), name="technical-area"),
]
