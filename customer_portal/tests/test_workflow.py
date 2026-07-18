from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from accounts.roles import ROLE_ATTENDANCE, ensure_roles
from orders.models import Company, Order, Product

from customer_portal.models import (
    CustomerDeliveryLocation,
    CustomerOrderRequest,
    CustomerOrderRequestItem,
    CustomerPortalAccess,
)
from customer_portal.review_state import start_review
from customer_portal.services import approve_and_convert_request, submit_request

pytestmark = pytest.mark.django_db


def test_review_state_and_http_approval_are_controlled(client):
    User = get_user_model()
    company = Company.objects.create(name="Empresa Workflow")
    location = CustomerDeliveryLocation.objects.create(
        company=company,
        label="Unidade",
        address="Rua Operacional, 10",
        city="Itabirito",
    )
    product = Product.objects.create(name="Marmita", unit_price=Decimal("20.00"))
    customer = User.objects.create_user(username="workflow_cliente", password="Senha123forte")
    reviewer = User.objects.create_user(username="workflow_atendimento", password="Senha123forte")
    CustomerPortalAccess.objects.create(user=customer, company=company)
    reviewer.groups.add(ensure_roles()[ROLE_ATTENDANCE])

    customer_request = CustomerOrderRequest.objects.create(
        creation_key="workflow-request-key",
        company=company,
        requested_by=customer,
        delivery_date=timezone.localdate() + timedelta(days=1),
        delivery_location=location,
    )
    CustomerOrderRequestItem.objects.create(
        request=customer_request,
        product=product,
        quantity=5,
        unit_price=product.unit_price,
    )
    submit_request(request_id=customer_request.pk, actor=customer)

    start_review(request_id=customer_request.pk, actor=reviewer)
    customer_request.refresh_from_db()
    assert customer_request.status == CustomerOrderRequest.Status.IN_REVIEW

    client.force_login(reviewer)
    response = client.post(
        reverse("customer_portal:request-approve", kwargs={"pk": customer_request.pk})
    )
    assert response.status_code == 302

    customer_request.refresh_from_db()
    assert customer_request.status == CustomerOrderRequest.Status.CONVERTED
    assert customer_request.converted_order_id is not None
    assert Order.objects.filter(creation_key=f"portal:{customer_request.pk}").count() == 1

    order, created = approve_and_convert_request(
        request_id=customer_request.pk,
        actor=reviewer,
    )
    assert created is False
    assert order.pk == customer_request.converted_order_id
