from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from accounts.roles import ROLE_ATTENDANCE, ensure_roles
from customer_portal.forms import CustomerRequestForm
from customer_portal.models import (
    CustomerDeliveryLocation,
    CustomerOrderRequest,
    CustomerOrderRequestItem,
    CustomerPortalAccess,
)
from customer_portal.services import (
    approve_and_convert_request,
    cancel_request,
    request_correction,
    submit_request,
)
from orders.models import AuditEvent, Company, Order, Product

pytestmark = pytest.mark.django_db


@pytest.fixture
def portal_data():
    User = get_user_model()
    company = Company.objects.create(name="Cliente Portal", active=True)
    other_company = Company.objects.create(name="Outro Cliente", active=True)
    location = CustomerDeliveryLocation.objects.create(
        company=company,
        label="Sede",
        address="Rua A, 100",
        city="Itabirito",
    )
    other_location = CustomerDeliveryLocation.objects.create(
        company=other_company,
        label="Outra sede",
        address="Rua B, 200",
        city="Itabirito",
    )
    product = Product.objects.create(
        name="Refeição executiva",
        category="Refeições",
        unit_price=Decimal("25.00"),
    )
    customer = User.objects.create_user(username="cliente", password="SenhaForte123")
    other_customer = User.objects.create_user(username="outro", password="SenhaForte123")
    reviewer = User.objects.create_user(username="atendimento", password="SenhaForte123")
    CustomerPortalAccess.objects.create(user=customer, company=company)
    CustomerPortalAccess.objects.create(user=other_customer, company=other_company)
    roles = ensure_roles()
    reviewer.groups.add(roles[ROLE_ATTENDANCE])
    return {
        "company": company,
        "other_company": other_company,
        "location": location,
        "other_location": other_location,
        "product": product,
        "customer": customer,
        "other_customer": other_customer,
        "reviewer": reviewer,
    }


def make_request(data, *, user_key="customer", status=CustomerOrderRequest.Status.DRAFT):
    customer = data[user_key]
    company = data["company"] if user_key == "customer" else data["other_company"]
    location = data["location"] if user_key == "customer" else data["other_location"]
    customer_request = CustomerOrderRequest.objects.create(
        creation_key=f"test-{customer.username}-{CustomerOrderRequest.objects.count()}",
        company=company,
        requested_by=customer,
        delivery_date=timezone.localdate() + timedelta(days=1),
        delivery_time="12:00",
        delivery_location=location,
        status=status,
    )
    CustomerOrderRequestItem.objects.create(
        request=customer_request,
        product=data["product"],
        quantity=10,
        unit_price=data["product"].unit_price,
    )
    customer_request.refresh_from_db()
    return customer_request


def test_login_and_root_redirect_customer_to_portal(client, portal_data):
    response = client.post(
        reverse("login"),
        {"username": "cliente", "password": "SenhaForte123"},
    )
    assert response.status_code == 302
    assert response.url == reverse("customer_portal:request-list")

    response = client.get(reverse("dashboard"))
    assert response.status_code == 302
    assert response.url == reverse("customer_portal:request-list")


def test_customer_cannot_read_request_from_other_company(client, portal_data):
    other_request = make_request(portal_data, user_key="other_customer")
    client.force_login(portal_data["customer"])

    response = client.get(
        reverse("customer_portal:request-detail", kwargs={"pk": other_request.pk})
    )
    assert response.status_code == 404


def test_form_rejects_delivery_location_from_another_company(portal_data):
    form = CustomerRequestForm(
        data={
            "creation_key": "a" * 32,
            "delivery_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "delivery_time": "12:00",
            "delivery_location": str(portal_data["other_location"].pk),
            "notes": "",
        },
        instance=CustomerOrderRequest(
            company=portal_data["company"],
            requested_by=portal_data["customer"],
        ),
        company=portal_data["company"],
    )
    assert not form.is_valid()
    assert "delivery_location" in form.errors


def test_submit_recalculates_current_server_price(portal_data):
    customer_request = make_request(portal_data)
    portal_data["product"].unit_price = Decimal("27.50")
    portal_data["product"].save(update_fields=("unit_price", "updated_at"))

    submit_request(request_id=customer_request.pk, actor=portal_data["customer"])

    customer_request.refresh_from_db()
    item = customer_request.items.get()
    assert customer_request.status == CustomerOrderRequest.Status.SUBMITTED
    assert item.unit_price == Decimal("27.50")
    assert item.line_total == Decimal("275.00")
    assert customer_request.total_amount == Decimal("275.00")
    assert customer_request.delivery_address_snapshot == "Rua A, 100, Itabirito"


def test_approval_creates_one_order_and_is_idempotent(portal_data):
    customer_request = make_request(portal_data)
    submit_request(request_id=customer_request.pk, actor=portal_data["customer"])

    order, created = approve_and_convert_request(
        request_id=customer_request.pk,
        actor=portal_data["reviewer"],
    )
    repeated_order, repeated_created = approve_and_convert_request(
        request_id=customer_request.pk,
        actor=portal_data["reviewer"],
    )

    customer_request.refresh_from_db()
    assert created is True
    assert repeated_created is False
    assert repeated_order.pk == order.pk
    assert Order.objects.filter(creation_key=f"portal:{customer_request.pk}").count() == 1
    assert customer_request.converted_order_id == order.pk
    assert customer_request.status == CustomerOrderRequest.Status.CONVERTED
    assert order.total_amount == customer_request.total_amount
    assert order.items.count() == customer_request.items.count()
    assert AuditEvent.objects.filter(action="customer_request.approved").count() == 1
    assert AuditEvent.objects.filter(action="customer_request.converted").count() == 1


def test_correction_and_client_cancellation_are_audited(portal_data):
    customer_request = make_request(portal_data)
    submit_request(request_id=customer_request.pk, actor=portal_data["customer"])

    request_correction(
        request_id=customer_request.pk,
        actor=portal_data["reviewer"],
        reason="Confirmar o horário.",
    )
    customer_request.refresh_from_db()
    assert customer_request.status == CustomerOrderRequest.Status.CORRECTION_REQUESTED

    cancel_request(request_id=customer_request.pk, actor=portal_data["customer"])
    customer_request.refresh_from_db()
    assert customer_request.status == CustomerOrderRequest.Status.CANCELLED
    assert AuditEvent.objects.filter(action="customer_request.cancelled").exists()


def test_only_reviewer_can_open_operational_queue(client, portal_data):
    client.force_login(portal_data["customer"])
    response = client.get(reverse("customer_portal:request-queue"))
    assert response.status_code == 403

    client.force_login(portal_data["reviewer"])
    response = client.get(reverse("customer_portal:request-queue"))
    assert response.status_code == 200
