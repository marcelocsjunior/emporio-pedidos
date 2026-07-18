from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from customer_portal.models import (
    CustomerDeliveryLocation,
    CustomerOrderRequest,
    CustomerOrderRequestItem,
)
from customer_portal.services import approve_and_convert_request
from orders.models import Company, Product

pytestmark = pytest.mark.django_db(transaction=True)


def test_approval_lock_does_not_join_nullable_converted_order():
    User = get_user_model()
    company = Company.objects.create(name="Empresa PostgreSQL", active=True)
    location = CustomerDeliveryLocation.objects.create(
        company=company,
        label="Sede",
        address="Rua de teste, 10",
        city="Itabirito",
    )
    product = Product.objects.create(
        name="Refeição PostgreSQL",
        unit_price=Decimal("25.00"),
        active=True,
    )
    customer = User.objects.create_user(username="cliente_pg")
    reviewer = User.objects.create_user(username="atendimento_pg")
    customer_request = CustomerOrderRequest.objects.create(
        creation_key="postgres-lock-regression",
        company=company,
        requested_by=customer,
        delivery_date=timezone.localdate() + timedelta(days=1),
        delivery_location=location,
        delivery_address_snapshot=location.full_address,
        status=CustomerOrderRequest.Status.SUBMITTED,
        submitted_at=timezone.now(),
    )
    CustomerOrderRequestItem.objects.create(
        request=customer_request,
        product=product,
        quantity=4,
        unit_price=product.unit_price,
    )

    with CaptureQueriesContext(connection) as captured:
        order, created = approve_and_convert_request(
            request_id=customer_request.pk,
            actor=reviewer,
        )

    request_selects = [
        query["sql"]
        for query in captured.captured_queries
        if 'FROM "customer_portal_customerorderrequest"' in query["sql"]
    ]

    assert created is True
    assert order.total_amount == Decimal("100.00")
    assert request_selects
    assert 'LEFT OUTER JOIN "orders_order"' not in request_selects[0]
