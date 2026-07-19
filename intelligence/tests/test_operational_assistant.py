from datetime import datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from customer_portal.models import (
    CustomerDeliveryLocation,
    CustomerOrderRequest,
    CustomerOrderRequestItem,
)
from intelligence.models import AIEvent, AIRecommendation
from intelligence.operational_assistant import (
    KIND_AUTHORIZATION,
    KIND_DELIVERY,
    build_operational_assistant,
)
from orders.models import AuditEvent, Company, Order, OrderItem, Product


class OperationalAssistantServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username="admin-assistente",
            password="Senha!123456",
            email="admin@example.invalid",
        )
        cls.customer = User.objects.create_user("cliente-servico", password="Senha!123456")
        cls.company = Company.objects.create(name="Empresa Serviço", active=True)
        cls.product = Product.objects.create(
            name="Refeição serviço",
            unit_price=Decimal("30.00"),
        )
        cls.location = CustomerDeliveryLocation.objects.create(
            company=cls.company,
            label="Unidade",
            address="Rua de Teste, 20",
            city="Itabirito",
        )
        cls.now = timezone.make_aware(datetime(2026, 7, 18, 10, 0))
        cls.order = Order.objects.create(
            company=cls.company,
            order_date=cls.now.date(),
            delivery_date=cls.now.date(),
            delivery_time=(cls.now + timedelta(minutes=20)).time(),
            status=Order.Status.IN_PRODUCTION,
            delivery_location=cls.location.full_address,
        )
        OrderItem.objects.create(
            order=cls.order,
            product=cls.product,
            quantity=4,
            unit_price=cls.product.unit_price,
        )
        cls.customer_request = CustomerOrderRequest.objects.create(
            creation_key="service-assistant-request",
            company=cls.company,
            requested_by=cls.customer,
            delivery_date=cls.now.date() + timedelta(days=1),
            delivery_time=cls.now.time(),
            delivery_location=cls.location,
            delivery_address_snapshot=cls.location.full_address,
            status=CustomerOrderRequest.Status.SUBMITTED,
            submitted_at=cls.now,
        )
        CustomerOrderRequestItem.objects.create(
            request=cls.customer_request,
            product=cls.product,
            quantity=2,
            unit_price=cls.product.unit_price,
        )

    def test_builds_read_only_priorities_with_existing_delay_rule(self):
        audit_count = AuditEvent.objects.count()
        event_count = AIEvent.objects.count()
        recommendation_count = AIRecommendation.objects.count()

        panel = build_operational_assistant(self.user, now=self.now)

        kinds = {card.kind for card in panel.cards}
        self.assertIn(KIND_AUTHORIZATION, kinds)
        self.assertIn(KIND_DELIVERY, kinds)
        delay_card = next(card for card in panel.cards if card.kind == KIND_DELIVERY)
        self.assertEqual(delay_card.severity, AIRecommendation.Severity.CRITICAL)
        self.assertIn(self.order.number, delay_card.title)
        self.assertEqual(AuditEvent.objects.count(), audit_count)
        self.assertEqual(AIEvent.objects.count(), event_count)
        self.assertEqual(AIRecommendation.objects.count(), recommendation_count)

    def test_delivered_order_is_not_returned(self):
        self.order.status = Order.Status.DELIVERED
        self.order.save(update_fields=("status", "updated_at"))

        panel = build_operational_assistant(self.user, now=self.now)

        self.assertNotIn(
            f"order:{self.order.pk}",
            {card.source_key for card in panel.cards},
        )
