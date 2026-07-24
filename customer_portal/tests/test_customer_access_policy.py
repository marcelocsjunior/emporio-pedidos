import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from accounts.models import UserCapabilityOverride
from accounts.roles import ROLE_ADMIN, ROLE_PRODUCTION
from customer_portal.access_policy import (
    CustomerAccessManagerMixin,
    can_manage_customer_access,
)
from customer_portal.access_views import (
    AccessRequestQueueView,
    AccessRequestReviewView,
    PortalAccessDetailView,
    PortalAccessListView,
    PortalAccessStatusView,
    PortalPasswordResetView,
    PortalUserCreateView,
    PortalUserLinkView,
)

pytestmark = pytest.mark.django_db
User = get_user_model()
DESIGNATED_USERNAMES = ("angela", "suporte", "ti")


@pytest.fixture(autouse=True)
def exact_customer_access_manager_policy(settings):
    settings.CUSTOMER_ACCESS_MANAGER_USERNAMES = DESIGNATED_USERNAMES


@pytest.mark.parametrize("username", DESIGNATED_USERNAMES)
def test_only_designated_active_users_can_open_customer_access_admin(client, username):
    user = User.objects.create_user(username=username, password="SenhaForte!2026")
    client.force_login(user)

    assert can_manage_customer_access(user)
    assert client.get(reverse("customer_portal:access-list")).status_code == 200
    assert client.get(reverse("customer_portal:access-create")).status_code == 200
    assert client.get(reverse("customer_portal:access-link")).status_code == 200
    assert client.get(reverse("customer_portal:access-request-queue")).status_code == 200


def test_non_designated_user_is_denied_even_with_manage_companies_override(client):
    user = User.objects.create_user(username="marlene", password="SenhaForte!2026")
    production, _ = Group.objects.get_or_create(name=ROLE_PRODUCTION)
    user.groups.add(production)
    UserCapabilityOverride.objects.create(
        user=user,
        capability="manage_companies",
        effect="allow",
    )
    client.force_login(user)

    assert not can_manage_customer_access(user)
    for route_name in (
        "customer_portal:access-list",
        "customer_portal:access-create",
        "customer_portal:access-link",
        "customer_portal:access-request-queue",
    ):
        assert client.get(reverse(route_name)).status_code == 403


def test_administrator_role_does_not_bypass_designated_user_policy(client):
    user = User.objects.create_user(username="diretoria", password="SenhaForte!2026")
    administrator, _ = Group.objects.get_or_create(name=ROLE_ADMIN)
    user.groups.add(administrator)
    client.force_login(user)

    response = client.get(reverse("dashboard"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Acessos dos clientes" not in body
    assert "Solicitações de acesso" not in body
    assert client.get(reverse("customer_portal:access-list")).status_code == 403


def test_designated_user_sees_customer_access_administration_menu(client):
    user = User.objects.create_user(username="angela", password="SenhaForte!2026")
    client.force_login(user)

    response = client.get(reverse("customer_portal:access-list"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Acessos dos clientes" in body
    assert "Solicitações de acesso" in body


def test_password_change_redirect_does_not_mean_backend_policy_denial(client):
    user = User.objects.create_user(
        username="angela",
        password="SenhaForte!2026",
        must_change_password=True,
    )
    client.force_login(user)

    assert can_manage_customer_access(user)
    response = client.get(reverse("customer_portal:access-list"))

    assert response.status_code == 302
    assert response.url == reverse("password_change")


def test_inactive_designated_user_is_denied():
    user = User.objects.create_user(username="suporte", is_active=False)

    assert not can_manage_customer_access(user)


@pytest.mark.parametrize(
    "view_class",
    (
        PortalAccessListView,
        PortalAccessDetailView,
        PortalUserCreateView,
        PortalUserLinkView,
        PortalAccessStatusView,
        PortalPasswordResetView,
        AccessRequestQueueView,
        AccessRequestReviewView,
    ),
)
def test_all_customer_access_operations_share_the_restricted_mixin(view_class):
    assert issubclass(view_class, CustomerAccessManagerMixin)
