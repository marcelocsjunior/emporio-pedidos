from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from orders.models import AuditEvent, Company, Order, OrderItem, Product
from orders.services import change_order_status, generate_monthly_closing

pytestmark = pytest.mark.django_db


@pytest.fixture
def company():
    return Company.objects.create(name="Mineração Alfa")


@pytest.fixture
def product():
    return Product.objects.create(name="Marmita completa", unit_price=Decimal("22.00"))


def test_order_item_uses_product_price_and_recalculates_order(company, product):
    order = Order.objects.create(
        company=company,
        order_date=date(2026, 7, 18),
        delivery_date=date(2026, 7, 18),
    )

    item = OrderItem.objects.create(
        order=order,
        product=product,
        quantity=5,
        unit_price=Decimal("0.00"),
    )

    order.refresh_from_db()
    assert item.product_name == "Marmita completa"
    assert item.unit_price == Decimal("22.00")
    assert item.line_total == Decimal("110.00")
    assert order.total_amount == Decimal("110.00")


def test_status_flow_is_controlled_and_audited(company):
    order = Order.objects.create(
        company=company,
        order_date=date(2026, 7, 18),
        delivery_date=date(2026, 7, 18),
    )

    change_order_status(
        order_id=order.id,
        new_status=Order.Status.RECEIVED,
        idempotency_key="status-1",
    )
    same_order = change_order_status(
        order_id=order.id,
        new_status=Order.Status.RECEIVED,
        idempotency_key="status-1",
    )

    order.refresh_from_db()
    assert same_order.pk == order.pk
    assert order.status == Order.Status.RECEIVED
    assert order.status_history.count() == 1
    audit_count = AuditEvent.objects.filter(
        entity_id=str(order.id), action="order.status_changed"
    ).count()
    assert audit_count == 1

    with pytest.raises(ValidationError):
        change_order_status(order_id=order.id, new_status=Order.Status.DELIVERED)


def test_monthly_closing_only_counts_delivered_orders(company, product):
    delivered = Order.objects.create(
        company=company,
        order_date=date(2026, 7, 1),
        delivery_date=date(2026, 7, 1),
        status=Order.Status.DELIVERED,
    )
    OrderItem.objects.create(
        order=delivered,
        product=product,
        quantity=10,
        unit_price=Decimal("22.00"),
    )

    cancelled = Order.objects.create(
        company=company,
        order_date=date(2026, 7, 2),
        delivery_date=date(2026, 7, 2),
        status=Order.Status.CANCELLED,
    )
    OrderItem.objects.create(
        order=cancelled,
        product=product,
        quantity=5,
        unit_price=Decimal("22.00"),
    )

    closing = generate_monthly_closing(
        company_id=company.id,
        reference_month=date(2026, 7, 18),
    )

    assert closing.reference_month == date(2026, 7, 1)
    assert closing.order_count == 1
    assert closing.item_count == 10
    assert closing.total_amount == Decimal("220.00")
    assert "R$ 220,00" in closing.message_snapshot
