from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from accounts.models import UserCapabilityOverride
from customer_portal.access_services import create_portal_user
from customer_portal.models import CustomerPortalAccess, CustomerPortalAccessRequest
from orders.models import AuditEvent, Company

User = get_user_model()
pytestmark = pytest.mark.django_db
VALID_CPF = "52998224725"
VALID_CNPJ = "11222333000181"


def valid_cpf(seed: int) -> str:
    digits = [int(digit) for digit in f"{seed:09d}"[-9:]]
    if len(set(digits)) == 1:
        digits[-1] = (digits[-1] + 1) % 10
    for start in (10, 11):
        total = sum(
            digit * weight
            for digit, weight in zip(digits, range(start, 1, -1), strict=False)
        )
        check = (total * 10) % 11
        digits.append(0 if check == 10 else check)
    return "".join(str(digit) for digit in digits)


def company(name="Cliente Fictício"):
    return Company.objects.create(name=name, entity_type=Company.EntityType.COMPANY)


def operator(username="operador"):
    user = User.objects.create_user(username=username, password="SenhaForte!2026")
    UserCapabilityOverride.objects.create(user=user, capability="manage_companies", effect="allow")
    return user


def public_payload(**changes):
    data = {
        "customer_name": "Empresa Exemplo Ltda",
        "entity_type": Company.EntityType.INDIVIDUAL,
        "document": VALID_CPF,
        "requester_name": "Pessoa Exemplo",
        "email": "PESSOA@EXAMPLE.COM",
        "phone": "(11) 99999-0000",
        "message": "Favor analisar.",
        "website": "",
    }
    data.update(changes)
    return data


def test_public_page_and_login_link(client):
    assert client.get(reverse("customer_portal:access-request-public")).status_code == 200
    login = client.get(reverse("login"))
    assert reverse("customer_portal:access-request-public") in login.content.decode()


@pytest.mark.parametrize(
    ("entity_type", "document"),
    [(Company.EntityType.INDIVIDUAL, VALID_CPF), (Company.EntityType.COMPANY, VALID_CNPJ)],
)
def test_valid_public_request_is_private_and_creates_no_access(client, entity_type, document):
    before_users = User.objects.count()
    before_companies = Company.objects.count()
    response = client.post(
        reverse("customer_portal:access-request-public"),
        public_payload(entity_type=entity_type, document=document),
    )
    assert response.status_code == 200
    assert "Solicitação registrada para análise" in response.content.decode()
    request = CustomerPortalAccessRequest.objects.get()
    assert document not in request.__dict__.values()
    assert request.document_last_four == document[-4:]
    assert request.email == "pessoa@example.com"
    assert request.phone == "11999990000"
    assert User.objects.count() == before_users
    assert Company.objects.count() == before_companies
    assert not CustomerPortalAccess.objects.exists()
    assert document not in str(AuditEvent.objects.get().payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"document": "11111111111"},
        {"email": "invalido"},
        {"customer_name": "x" * 181},
        {"phone": "123"},
    ],
)
def test_public_validation_rejects_invalid_or_oversized_fields(client, changes):
    response = client.post(
        reverse("customer_portal:access-request-public"), public_payload(**changes)
    )
    assert response.status_code == 400
    assert not CustomerPortalAccessRequest.objects.exists()


def test_public_response_does_not_enumerate_company_or_email(client):
    Company.objects.create(
        name="Empresa Exemplo Ltda", document=VALID_CPF, entity_type=Company.EntityType.INDIVIDUAL
    )
    User.objects.create_user(username="existente", email="pessoa@example.com")
    response = client.post(reverse("customer_portal:access-request-public"), public_payload())
    body = response.content.decode()
    assert "Solicitação registrada para análise" in body
    assert "já existe" not in body.lower()


def test_public_idempotency_and_honeypot_are_explicit(client):
    url = reverse("customer_portal:access-request-public")
    first = client.post(url, public_payload())
    duplicate = client.post(url, public_payload())
    assert first.status_code == duplicate.status_code == 200
    assert "Solicitação registrada para análise" in first.content.decode()
    assert "Já existe uma solicitação recente" in duplicate.content.decode()
    assert CustomerPortalAccessRequest.objects.count() == 1
    honeypot = client.post(url, public_payload(email="outra@example.com", website="bot"))
    assert honeypot.status_code == 200
    assert "Não foi possível registrar" in honeypot.content.decode()
    assert CustomerPortalAccessRequest.objects.count() == 1


def test_public_abuse_limit_is_scoped_to_network_and_document(client):
    url = reverse("customer_portal:access-request-public")
    responses = []
    for number in range(7):
        responses.append(
            client.post(
                url,
                public_payload(email=f"p{number}@example.com", phone=f"1199999{number:04d}"),
                REMOTE_ADDR="198.51.100.10",
            )
        )
    assert all(response.status_code == 200 for response in responses)
    assert CustomerPortalAccessRequest.objects.count() == 5
    assert "Não foi possível registrar" in responses[-1].content.decode()


def test_shared_network_does_not_hide_distinct_customers(client):
    url = reverse("customer_portal:access-request-public")
    for number in range(1, 8):
        response = client.post(
            url,
            public_payload(
                customer_name=f"Cliente {number}",
                document=valid_cpf(number),
                email=f"cliente{number}@example.com",
                phone=f"1198888{number:04d}",
            ),
            REMOTE_ADDR="203.0.113.25",
        )
        assert response.status_code == 200
        assert "Solicitação registrada para análise" in response.content.decode()
    assert CustomerPortalAccessRequest.objects.count() == 7


def test_terminal_request_allows_new_submission(client):
    url = reverse("customer_portal:access-request-public")
    client.post(url, public_payload())
    previous = CustomerPortalAccessRequest.objects.get()
    previous.status = CustomerPortalAccessRequest.Status.REJECTED
    previous.save(update_fields=("status",))

    response = client.post(url, public_payload())

    assert response.status_code == 200
    assert "Solicitação registrada para análise" in response.content.decode()
    assert CustomerPortalAccessRequest.objects.count() == 2


def test_internal_list_requires_manage_companies(client):
    user = User.objects.create_user(username="sem-acesso", password="SenhaForte!2026")
    client.force_login(user)
    assert client.get(reverse("customer_portal:access-list")).status_code == 403
    allowed = operator()
    client.force_login(allowed)
    assert client.get(reverse("customer_portal:access-list")).status_code == 200


def test_access_request_company_filter_includes_unlinked_document_match(client):
    target_company = Company.objects.create(
        name="Cliente com documento",
        document=VALID_CPF,
        entity_type=Company.EntityType.INDIVIDUAL,
    )
    client.post(reverse("customer_portal:access-request-public"), public_payload())
    client.force_login(operator())

    response = client.get(
        reverse("customer_portal:access-request-queue"), {"company": target_company.pk}
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "Empresa Exemplo Ltda" in body
    assert f'value="{target_company.pk}" selected' in body
    assert "Limpar filtros" in body


def test_rafa_deny_is_preserved(client):
    rafa = User.objects.create_user(username="rafa", password="SenhaForte!2026")
    group, _ = Group.objects.get_or_create(name="Administrador")
    rafa.groups.add(group)
    UserCapabilityOverride.objects.create(user=rafa, capability="manage_companies", effect="deny")
    client.force_login(rafa)
    assert client.get(reverse("customer_portal:access-list")).status_code == 403


def test_root_ti_is_authorized_without_changing_existing_permissions(client):
    ti = User.objects.create_superuser(
        username="ti", email="ti@example.invalid", password="SenhaForte!2026"
    )
    client.force_login(ti)
    assert client.get(reverse("customer_portal:access-list")).status_code == 200


def test_internal_user_creation_hashes_password_and_grants_no_privileges(client):
    actor = operator()
    target_company = company()
    client.force_login(actor)
    password = "SenhaPortal!2026"
    response = client.post(
        reverse("customer_portal:access-create"),
        {
            "company": target_company.pk,
            "username": "cliente.portal",
            "first_name": "Cliente",
            "last_name": "Portal",
            "email": "CLIENTE@example.com",
            "password1": password,
            "password2": password,
            "active": "on",
        },
    )
    assert response.status_code == 302
    user = User.objects.get(username="cliente.portal")
    assert user.check_password(password)
    assert not user.is_staff and not user.is_superuser
    assert not user.groups.exists() and not user.user_permissions.exists()
    assert user.must_change_password
    assert password not in str(list(AuditEvent.objects.values_list("payload", flat=True)))


def test_duplicate_email_and_protected_users_are_blocked(client):
    actor = operator()
    target_company = company()
    User.objects.create_user(username="old", email="same@example.com")
    client.force_login(actor)
    response = client.post(
        reverse("customer_portal:access-create"),
        {
            "company": target_company.pk,
            "username": "new",
            "email": "SAME@example.com",
            "password1": "SenhaPortal!2026",
            "password2": "SenhaPortal!2026",
            "active": "on",
        },
    )
    assert response.status_code == 400
    for username in ("ti", "bio", "rafa"):
        protected = User.objects.create_user(username=username)
        response = client.post(
            reverse("customer_portal:access-link"),
            {"company": target_company.pk, "user": protected.pk, "active": "on", "confirm": "on"},
        )
        assert response.status_code == 400


@pytest.mark.parametrize("flags", [{"is_staff": True}, {"is_superuser": True}])
def test_staff_and_superuser_link_are_blocked(client, flags):
    actor = operator()
    target_company = company()
    user = User.objects.create_user(username=f"admin-{len(flags)}", **flags)
    client.force_login(actor)
    response = client.post(
        reverse("customer_portal:access-link"),
        {"company": target_company.pk, "user": user.pk, "active": "on", "confirm": "on"},
    )
    assert response.status_code == 400
    assert not CustomerPortalAccess.objects.filter(user=user).exists()


def test_existing_user_link_activation_revocation_and_password_reset(client):
    actor = operator()
    target_company = company()
    user = User.objects.create_user(username="cliente-existente", password="SenhaAnterior!2026")
    client.force_login(actor)
    response = client.post(
        reverse("customer_portal:access-link"),
        {"company": target_company.pk, "user": user.pk, "active": "on", "confirm": "on"},
    )
    access = CustomerPortalAccess.objects.get(user=user)
    assert response.status_code == 302 and access.active
    response = client.post(
        reverse("customer_portal:access-status", args=(access.pk, "revoke")),
        {"reason": "Solicitação operacional", "confirm": "on"},
    )
    access.refresh_from_db()
    assert response.status_code == 302 and not access.active
    assert User.objects.filter(pk=user.pk).exists()
    response = client.post(
        reverse("customer_portal:access-status", args=(access.pk, "activate")), {"confirm": "on"}
    )
    access.refresh_from_db()
    assert access.active
    new_password = "NovaSenhaPortal!2026"
    client.post(
        reverse("customer_portal:access-password-reset", args=(access.pk,)),
        {"password1": new_password, "password2": new_password},
    )
    user.refresh_from_db()
    assert user.check_password(new_password)
    assert new_password not in str(list(AuditEvent.objects.values_list("payload", flat=True)))


def test_human_review_requires_company_user_confirmation_and_rejection_reason(client):
    actor = operator()
    target_company = company()
    user = User.objects.create_user(username="solicitante")
    client.force_login(actor)
    client.post(reverse("customer_portal:access-request-public"), public_payload())
    request = CustomerPortalAccessRequest.objects.get()
    url = reverse("customer_portal:access-request-review", args=(request.pk,))
    assert client.post(url, {"action": "approve", "confirm": "on"}).status_code == 400
    assert (
        client.post(
            url, {"action": "approve", "company": target_company.pk, "user": user.pk}
        ).status_code
        == 400
    )
    response = client.post(
        url, {"action": "approve", "company": target_company.pk, "user": user.pk, "confirm": "on"}
    )
    request.refresh_from_db()
    assert response.status_code == 302
    assert request.status == CustomerPortalAccessRequest.Status.APPROVED
    assert CustomerPortalAccess.objects.filter(user=user, company=target_company).exists()

    client.post(
        reverse("customer_portal:access-request-public"), public_payload(email="reject@example.com")
    )
    rejected = CustomerPortalAccessRequest.objects.exclude(pk=request.pk).get()
    reject_url = reverse("customer_portal:access-request-review", args=(rejected.pk,))
    assert client.post(reject_url, {"action": "reject", "confirm": "on"}).status_code == 400
    assert (
        client.post(
            reject_url,
            {"action": "reject", "confirm": "on", "decision_notes": "Identidade não comprovada."},
        ).status_code
        == 302
    )
    rejected.refresh_from_db()
    assert rejected.status == CustomerPortalAccessRequest.Status.REJECTED


def test_user_and_access_creation_is_atomic_when_audit_fails():
    actor = operator()
    target_company = company()
    from customer_portal.access_forms import PortalUserCreateForm

    form = PortalUserCreateForm(
        {
            "company": target_company.pk,
            "username": "rollback",
            "email": "rollback@example.com",
            "password1": "SenhaPortal!2026",
            "password2": "SenhaPortal!2026",
            "active": "on",
        }
    )
    assert form.is_valid(), form.errors
    with patch("customer_portal.access_services.record_audit", side_effect=RuntimeError):
        with pytest.raises(RuntimeError):
            create_portal_user(form=form, actor=actor)
    assert not User.objects.filter(username="rollback").exists()
    assert not CustomerPortalAccess.objects.exists()
