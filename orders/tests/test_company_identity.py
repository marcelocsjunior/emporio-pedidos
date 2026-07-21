from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from orders.forms import CompanyForm
from orders.models import Company

pytestmark = pytest.mark.django_db


def company_payload(**overrides) -> dict[str, str]:
    payload = {
        "name": "Cliente Identificado",
        "entity_type": Company.EntityType.COMPANY,
        "document": "11.222.333/0001-81",
        "responsible_name": "Responsável",
        "phone": "31999990000",
        "email": " Financeiro@Exemplo.com.br ",
        "address": "Rua de Teste, 10",
        "city": "Itabirito",
        "state": "mg",
        "postal_code": "35.450-000",
        "customer_type": Company.CustomerType.MONTHLY,
        "payment_terms": "30 dias",
        "source_system": " ERP-Legado ",
        "external_id": " CLI-001 ",
        "notes": "",
    }
    payload.update(overrides)
    return payload


def test_company_form_normalizes_and_persists_customer_identity():
    form = CompanyForm(data=company_payload())

    assert form.is_valid(), form.errors
    company = form.save()

    assert company.entity_type == Company.EntityType.COMPANY
    assert company.document == "11222333000181"
    assert company.email == "financeiro@exemplo.com.br"
    assert company.state == "MG"
    assert company.postal_code == "35450000"
    assert company.source_system == "erp-legado"
    assert company.external_id == "CLI-001"
    assert company.masked_document == "**.***.***/****-81"


def test_individual_customer_requires_valid_cpf():
    company = Company(
        name="Pessoa Física",
        entity_type=Company.EntityType.INDIVIDUAL,
        document="11.222.333/0001-81",
    )

    with pytest.raises(ValidationError) as exc_info:
        company.full_clean()

    assert "document" in exc_info.value.message_dict


def test_company_rejects_letters_in_document_and_postal_code():
    form = CompanyForm(
        data=company_payload(
            name="Cliente com identificadores inválidos",
            document="CNPJ desconhecido",
            postal_code="CEP inválido",
        )
    )

    assert not form.is_valid()
    assert "document" in form.errors
    assert "postal_code" in form.errors


def test_company_rejects_invalid_state_postal_code_and_incomplete_external_identity():
    company = Company(
        name="Cliente Inválido",
        state="M1",
        postal_code="123",
        source_system="erp",
    )

    with pytest.raises(ValidationError) as exc_info:
        company.full_clean()

    errors = exc_info.value.message_dict
    assert "state" in errors
    assert "postal_code" in errors
    assert "external_id" in errors


def test_document_uniqueness_uses_normalized_value():
    first = Company(
        name="Primeiro CNPJ",
        entity_type=Company.EntityType.COMPANY,
        document="11.222.333/0001-81",
    )
    first.full_clean()
    first.save()

    with pytest.raises(IntegrityError), transaction.atomic():
        Company.objects.create(
            name="Segundo CNPJ",
            entity_type=Company.EntityType.COMPANY,
            document="11222333000181",
        )


def test_source_and_external_id_pair_is_unique():
    Company.objects.create(
        name="Origem Um",
        source_system="ERP",
        external_id="001",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Company.objects.create(
            name="Origem Dois",
            source_system="erp",
            external_id="001",
        )


def test_existing_company_defaults_to_legal_entity_without_document():
    company = Company.objects.create(name="Cadastro Existente")

    assert company.entity_type == Company.EntityType.COMPANY
    assert company.document == ""
    assert company.customer_type == Company.CustomerType.SPOT


def test_company_form_preserves_legacy_payload_default():
    payload = company_payload(name="Cadastro Legado")
    payload.pop("entity_type")

    form = CompanyForm(data=payload)

    assert form.is_valid(), form.errors
    company = form.save()
    assert company.entity_type == Company.EntityType.COMPANY
