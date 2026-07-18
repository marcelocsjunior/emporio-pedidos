from datetime import timedelta
from pathlib import Path

import pytest
from customer_portal.models import (
    CustomerDeliveryLocation,
    CustomerOrderRequest,
    CustomerPortalAccess,
)
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse
from django.utils import timezone
from orders.models import Company

pytestmark = pytest.mark.django_db


def test_request_list_exposes_mobile_card_semantics(client):
    user = get_user_model().objects.create_user(username="cliente-mobile")
    company = Company.objects.create(name="Cliente mobile", active=True)
    location = CustomerDeliveryLocation.objects.create(
        company=company,
        label="Sede",
        address="Rua A, 100",
        city="Itabirito",
    )
    CustomerPortalAccess.objects.create(user=user, company=company)
    CustomerOrderRequest.objects.create(
        creation_key="mobile-layout-test",
        company=company,
        requested_by=user,
        delivery_date=timezone.localdate() + timedelta(days=1),
        delivery_time="12:00",
        delivery_location=location,
    )

    client.force_login(user)
    response = client.get(reverse("customer_portal:request-list"))
    html = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "css/customer_portal.css" in html
    assert 'class="page-heading portal-request-heading"' in html
    assert 'class="button primary portal-request-create"' in html
    assert 'class="responsive-table portal-request-table"' in html
    for label in ("Protocolo", "Entrega", "Status", "Total", "Pedido", "Ação"):
        assert f'data-label="{label}"' in html
    assert 'class="portal-request-action"' in html


def test_portal_mobile_css_preserves_action_from_accessibility_overlay():
    css_path = finders.find("css/customer_portal.css")

    assert css_path is not None
    css = Path(css_path).read_text(encoding="utf-8")
    assert "@media (max-width: 700px)" in css
    assert ".portal-request-heading > .portal-request-create" in css
    assert "grid-template-columns: minmax(88px, 34%) minmax(0, 1fr)" in css
    assert "padding: 12px 84px 2px 0" in css
    assert "orientation: landscape" in css
    assert "padding-right: 96px" in css
