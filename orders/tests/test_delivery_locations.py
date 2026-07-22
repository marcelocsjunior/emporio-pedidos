from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from accounts.roles import ROLE_ADMIN, ensure_roles
from customer_portal.forms import CustomerRequestForm
from customer_portal.models import (
    CustomerDeliveryLocation,
    CustomerOrderRequest,
    CustomerPortalAccess,
)
from orders.company_imports import (
    ImportFileError,
    ParsedFile,
    apply_preview,
    execute_import,
    parse_csv,
    parse_xml,
    preview_rows,
    rollback_batch,
)
from orders.models import AuditEvent, Company, CompanyImportBatch

pytestmark = pytest.mark.django_db


@pytest.fixture
def location_data():
    user_model = get_user_model()
    admin = user_model.objects.create_user(username="location-admin")
    admin.groups.add(ensure_roles()[ROLE_ADMIN])
    company = Company.objects.create(name="Empresa técnica de locais")
    return admin, company


def test_manual_management_supports_multiple_locations_and_audit(client, location_data):
    admin, company = location_data
    client.force_login(admin)
    create_url = reverse("company-delivery-location-create", args=[company.pk])

    for label in ("Portaria 1", "Portaria 2", "Administrativo"):
        response = client.post(
            create_url,
            {"label": label, "address": f"Rua Técnica, {label[-1]}", "city": "Cidade Teste"},
        )
        assert response.status_code == 302

    assert company.customer_delivery_locations.count() == 3
    assert AuditEvent.objects.filter(action="delivery_location.created").count() == 3

    location = company.customer_delivery_locations.get(label="Portaria 1")
    edit_url = reverse("company-delivery-location-update", args=[company.pk, location.pk])
    response = client.post(
        edit_url,
        {"label": "Portaria Principal", "address": "Rua Técnica, 10", "city": ""},
    )
    assert response.status_code == 302
    location.refresh_from_db()
    assert location.label == "Portaria Principal"
    assert AuditEvent.objects.filter(action="delivery_location.updated").exists()

    toggle_url = reverse("company-delivery-location-toggle", args=[company.pk, location.pk])
    assert client.post(toggle_url).status_code == 302
    location.refresh_from_db()
    assert location.active is False
    assert AuditEvent.objects.filter(action="delivery_location.deactivated").exists()


def test_invalid_company_edit_preserves_existing_delivery_locations(client, location_data):
    admin, company = location_data
    locations = [
        CustomerDeliveryLocation.objects.create(
            company=company,
            label=label,
            address=address,
        )
        for label, address in (
            ("Portaria Norte", "Rua Norte, 10"),
            ("Recepção Sul", "Rua Sul, 20"),
        )
    ]
    before = list(
        company.customer_delivery_locations.order_by("pk").values(
            "pk", "label", "address", "city", "active"
        )
    )
    client.force_login(admin)

    response = client.post(reverse("company-update", args=[company.pk]), {"name": ""})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Este campo é obrigatório." in content
    for location in locations:
        assert location.label in content
    assert "Nenhum local de entrega cadastrado." not in content
    assert list(
        company.customer_delivery_locations.order_by("pk").values(
            "pk", "label", "address", "city", "active"
        )
    ) == before


def test_location_label_uniqueness_is_scoped_to_company(client, location_data):
    admin, company = location_data
    other = Company.objects.create(name="Outra empresa técnica")
    CustomerDeliveryLocation.objects.create(company=company, label="Recepção", address="Rua A")
    client.force_login(admin)

    duplicate = client.post(
        reverse("company-delivery-location-create", args=[company.pk]),
        {"label": "Recepção", "address": "Rua B", "city": ""},
    )
    allowed = client.post(
        reverse("company-delivery-location-create", args=[other.pk]),
        {"label": "Recepção", "address": "Rua C", "city": ""},
    )

    assert duplicate.status_code == 200
    assert "Já existe um local" in duplicate.content.decode()
    assert allowed.status_code == 302


def test_location_management_requires_manage_companies(client, location_data):
    _, company = location_data
    user = get_user_model().objects.create_user(username="without-capability")
    client.force_login(user)
    response = client.get(reverse("company-delivery-location-create", args=[company.pk]))
    assert response.status_code == 403


def _draft(company):
    return CustomerOrderRequest(company=company, requested_by=get_user_model()())


def test_portal_location_empty_single_multiple_and_isolation():
    company = Company.objects.create(name="Portal técnico")
    other = Company.objects.create(name="Portal técnico externo")

    empty_form = CustomerRequestForm(instance=_draft(company), company=company)
    assert empty_form.no_active_delivery_locations is True

    first = CustomerDeliveryLocation.objects.create(
        company=company, label="Único", address="Rua Única"
    )
    single_form = CustomerRequestForm(instance=_draft(company), company=company)
    assert single_form.initial["delivery_location"] == first.pk

    second = CustomerDeliveryLocation.objects.create(
        company=company, label="Segundo", address="Rua Segunda"
    )
    inactive = CustomerDeliveryLocation.objects.create(
        company=company, label="Inativo", address="Rua Inativa", active=False
    )
    foreign = CustomerDeliveryLocation.objects.create(
        company=other, label="Externo", address="Rua Externa"
    )
    multiple_form = CustomerRequestForm(instance=_draft(company), company=company)
    ids = set(multiple_form.fields["delivery_location"].queryset.values_list("pk", flat=True))
    assert ids == {first.pk, second.pk}
    assert inactive.pk not in ids
    assert foreign.pk not in ids
    assert multiple_form.initial["delivery_location"] is None


def test_existing_editable_request_preserves_inactive_location():
    company = Company.objects.create(name="Portal preservação")
    user = get_user_model().objects.create_user(username="portal-preserve")
    location = CustomerDeliveryLocation.objects.create(
        company=company, label="Legado", address="Rua Legado", active=False
    )
    request = CustomerOrderRequest(
        company=company,
        requested_by=user,
        creation_key="preserve-location",
        delivery_date=timezone.localdate() + timedelta(days=1),
        delivery_location=location,
    )
    form = CustomerRequestForm(instance=request, company=company)
    assert location in form.fields["delivery_location"].queryset


def _batch(actor, parsed):
    return CompanyImportBatch.objects.create(
        created_by=actor,
        original_filename=f"delivery.{parsed.file_format}",
        file_hash=f"hash-{parsed.file_format}-{CompanyImportBatch.objects.count()}",
        file_format=parsed.file_format,
    )


def _mapping(parsed):
    return {header: header for header in parsed.headers}


@pytest.mark.parametrize(
    "parsed",
    [
        parse_csv(
            b"name,delivery_location_label,delivery_location_address,delivery_location_city\n"
            b"Empresa CSV,Portaria,Rua CSV,Cidade CSV\n"
        ),
        parse_xml(
            b"<companies><company><name>Empresa XML</name>"
            b"<delivery_location_label>Portaria</delivery_location_label>"
            b"<delivery_location_address>Rua XML</delivery_location_address>"
            b"<delivery_location_city>Cidade XML</delivery_location_city>"
            b"</company></companies>"
        ),
    ],
)
def test_import_creates_company_and_location_and_safe_rollback(parsed):
    actor = get_user_model().objects.create_user(username=f"import-{parsed.file_format}")
    batch = _batch(actor, parsed)
    apply_preview(batch, parsed, _mapping(parsed), actor)
    assert execute_import(batch, parsed, actor) == 1
    company = batch.items.get().company
    assert company.customer_delivery_locations.filter(label="Portaria").exists()
    assert AuditEvent.objects.filter(
        action="company_import.delivery_location_created",
        payload__batch_id=str(batch.pk),
    ).exists()

    assert rollback_batch(batch, actor) == 1
    assert not Company.objects.filter(pk=company.pk).exists()
    assert not CustomerDeliveryLocation.objects.filter(company_id=company.pk).exists()


@pytest.mark.parametrize(
    ("location_values", "expected_status"),
    [
        ({}, "valid"),
        (
            {
                "delivery_location_label": "Portaria",
                "delivery_location_address": "Rua Completa",
            },
            "valid",
        ),
        (
            {
                "delivery_location_label": "Portaria",
                "delivery_location_address": "Rua Completa",
                "delivery_location_city": "Cidade Completa",
            },
            "valid",
        ),
        ({"delivery_location_label": "Só label"}, "invalid"),
        ({"delivery_location_address": "Só endereço"}, "invalid"),
        ({"delivery_location_city": "Só cidade"}, "invalid"),
        (
            {
                "delivery_location_label": "Sem endereço",
                "delivery_location_city": "Cidade",
            },
            "invalid",
        ),
        (
            {
                "delivery_location_address": "Sem identificação",
                "delivery_location_city": "Cidade",
            },
            "invalid",
        ),
    ],
)
def test_import_validates_every_delivery_location_field_combination(
    location_values, expected_status
):
    values = {"name": "Contrato do local", **location_values}
    parsed = ParsedFile(headers=list(values), rows=[values], file_format="csv")

    row = preview_rows(parsed, _mapping(parsed))[0]

    assert row.status == expected_status
    if expected_status == "invalid":
        assert "cidade é opcional" in row.reason


@pytest.mark.parametrize(
    "parsed",
    [
        parse_csv(
            b"name,delivery_location_city\n"
            b"Empresa CSV com cidade isolada,Cidade CSV\n"
        ),
        parse_xml(
            b"<companies><company><name>Empresa XML com cidade isolada</name>"
            b"<delivery_location_city>Cidade XML</delivery_location_city>"
            b"</company></companies>"
        ),
    ],
)
def test_csv_and_xml_reject_isolated_delivery_location_city_without_importing(parsed):
    actor = get_user_model().objects.create_user(username=f"partial-{parsed.file_format}")
    batch = _batch(actor, parsed)

    rows = apply_preview(batch, parsed, _mapping(parsed), actor)

    assert rows[0].status == "invalid"
    assert "cidade é opcional" in rows[0].reason
    assert execute_import(batch, parsed, actor) == 0
    assert batch.items.count() == 0
    assert CustomerDeliveryLocation.objects.count() == 0


def test_import_allows_company_without_location():
    actor = get_user_model().objects.create_user(username="import-contract")
    without = ParsedFile(headers=["name"], rows=[{"name": "Sem local"}], file_format="csv")
    batch = _batch(actor, without)
    apply_preview(batch, without, _mapping(without), actor)
    execute_import(batch, without, actor)
    assert batch.items.get().company.customer_delivery_locations.count() == 0


def test_import_rollback_blocks_operational_portal_link():
    actor = get_user_model().objects.create_user(username="import-block")
    parsed = ParsedFile(headers=["name"], rows=[{"name": "Com vínculo"}], file_format="csv")
    batch = _batch(actor, parsed)
    apply_preview(batch, parsed, _mapping(parsed), actor)
    execute_import(batch, parsed, actor)
    company = batch.items.get().company
    portal_user = get_user_model().objects.create_user(username="linked-portal")
    CustomerPortalAccess.objects.create(user=portal_user, company=company)

    with pytest.raises(ImportFileError):
        rollback_batch(batch, actor)
    batch.refresh_from_db()
    assert batch.status == CompanyImportBatch.Status.ROLLBACK_BLOCKED
    assert Company.objects.filter(pk=company.pk).exists()
    assert company.customer_delivery_locations.count() == 0
    assert AuditEvent.objects.filter(action="company_import.rollback_blocked").count() == 1


def test_blocked_import_rollback_rechecks_links_on_every_attempt():
    actor = get_user_model().objects.create_user(username="import-retry")
    parsed = parse_csv(
        b"name,delivery_location_label,delivery_location_address\n"
        b"Empresa retry,Portaria,Rua Retry\n"
    )
    batch = _batch(actor, parsed)
    apply_preview(batch, parsed, _mapping(parsed), actor)
    execute_import(batch, parsed, actor)
    company = batch.items.get().company
    location_id = company.customer_delivery_locations.get().pk
    portal_user = get_user_model().objects.create_user(username="linked-retry")
    access = CustomerPortalAccess.objects.create(user=portal_user, company=company)

    for expected_audits in (1, 2):
        with pytest.raises(ImportFileError):
            rollback_batch(batch, actor)
        batch.refresh_from_db()
        assert batch.status == CompanyImportBatch.Status.ROLLBACK_BLOCKED
        assert Company.objects.filter(pk=company.pk).exists()
        assert CustomerDeliveryLocation.objects.filter(pk=location_id).exists()
        assert AuditEvent.objects.filter(
            action="company_import.rollback_blocked",
            entity_id=str(batch.pk),
        ).count() == expected_audits

    access.delete()

    assert rollback_batch(batch, actor) == 1
    batch.refresh_from_db()
    assert batch.status == CompanyImportBatch.Status.ROLLED_BACK
    assert batch.rollback_by == actor
    assert batch.rollback_at is not None
    assert not Company.objects.filter(pk=company.pk).exists()
    assert not CustomerDeliveryLocation.objects.filter(pk=location_id).exists()
    assert AuditEvent.objects.filter(
        action="company_import.rolled_back",
        entity_id=str(batch.pk),
    ).count() == 1

    with pytest.raises(ImportFileError):
        rollback_batch(batch, actor)
    assert AuditEvent.objects.filter(
        action="company_import.rolled_back",
        entity_id=str(batch.pk),
    ).count() == 1
