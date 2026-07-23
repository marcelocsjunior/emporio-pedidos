import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import UserCapabilityOverride
from customer_portal.models import CustomerPortalAccessRequest

pytestmark = pytest.mark.django_db
User = get_user_model()


def test_disabled_mode_hides_public_link_from_login(client, settings):
    settings.PUBLIC_ACCESS_REQUEST_ENABLED = False

    response = client.get(reverse("login"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Solicitar acesso" not in body
    assert "Novos acessos são criados exclusivamente" in body


def test_disabled_mode_replaces_direct_form_with_guidance(client, settings):
    settings.PUBLIC_ACCESS_REQUEST_ENABLED = False

    response = client.get(reverse("customer_portal:access-request-public"))
    body = response.content.decode()

    assert response.status_code == 200
    assert "exclusivamente pela equipe responsável do Empório" in body
    assert "Enviar solicitação" not in body
    assert "<form" not in body


def test_disabled_mode_rejects_post_without_creating_request(client, settings):
    settings.PUBLIC_ACCESS_REQUEST_ENABLED = False

    response = client.post(
        reverse("customer_portal:access-request-public"),
        {
            "customer_name": "Tentativa bloqueada",
            "entity_type": "individual",
            "document": "52998224725",
            "requester_name": "Solicitante",
            "email": "bloqueado@example.invalid",
            "phone": "31999990000",
            "website": "",
        },
    )

    assert response.status_code == 403
    assert "exclusivamente pela equipe responsável do Empório" in response.content.decode()
    assert not CustomerPortalAccessRequest.objects.exists()


def test_disabled_mode_keeps_internal_access_management_available(client, settings):
    settings.PUBLIC_ACCESS_REQUEST_ENABLED = False
    operator = User.objects.create_user(username="operador-flag", password="SenhaForte!2026")
    UserCapabilityOverride.objects.create(
        user=operator,
        capability="manage_companies",
        effect="allow",
    )
    client.force_login(operator)

    assert client.get(reverse("customer_portal:access-list")).status_code == 200
    assert client.get(reverse("customer_portal:access-create")).status_code == 200
    assert client.get(reverse("customer_portal:access-link")).status_code == 200
    assert client.get(reverse("customer_portal:access-request-queue")).status_code == 200


def test_enabled_mode_preserves_original_public_flow(client, settings):
    settings.PUBLIC_ACCESS_REQUEST_ENABLED = True

    login = client.get(reverse("login"))
    public_page = client.get(reverse("customer_portal:access-request-public"))

    assert reverse("customer_portal:access-request-public") in login.content.decode()
    assert public_page.status_code == 200
    assert "Enviar solicitação" in public_page.content.decode()
