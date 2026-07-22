from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import ROLE_COMMERCIAL, ensure_roles
from customer_portal.models import (
    CustomerDeliveryLocation,
    CustomerOrderRequest,
    CustomerOrderRequestItem,
)
from intelligence.active_assistant import CATEGORY_NEW_ORDER, EVENT_TYPE_ORDER_CREATED
from intelligence.models import AIEvent, AIRecommendation
from orders.models import Company, Product


@override_settings(
    AI_ACTIVE_ASSISTANT_ENABLED=True,
    AI_ACTIVE_ASSISTANT_PROMPT_VERSION="mvp-ia-03-portal-test",
)
class PortalActiveOrderNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_roles()
        cls.reviewer = User.objects.create_user(
            "revisor-ativo",
            password="Senha!123456",
        )
        cls.reviewer.groups.add(Group.objects.get(name=ROLE_COMMERCIAL))
        cls.customer = User.objects.create_user(
            "cliente-ativo",
            password="Senha!123456",
        )
        cls.company = Company.objects.create(name="Empresa Portal", active=True)
        cls.location = CustomerDeliveryLocation.objects.create(
            company=cls.company,
            label="Sede",
            address="Rua do Portal, 10",
            city="Itabirito",
        )
        cls.product = Product.objects.create(
            name="Refeição portal",
            unit_price=Decimal("28.00"),
        )

    def setUp(self):
        self.customer_request = CustomerOrderRequest.objects.create(
            creation_key="active-assistant-portal-request",
            company=self.company,
            requested_by=self.customer,
            delivery_date=timezone.localdate() + timedelta(days=1),
            delivery_time=timezone.localtime().time(),
            delivery_location=self.location,
            delivery_address_snapshot=self.location.full_address,
            status=CustomerOrderRequest.Status.SUBMITTED,
            submitted_at=timezone.now(),
        )
        CustomerOrderRequestItem.objects.create(
            request=self.customer_request,
            product=self.product,
            quantity=4,
            unit_price=self.product.unit_price,
        )
        self.customer_request.refresh_from_db()

    def test_approval_creates_one_immediate_notification(self):
        self.client.force_login(self.reviewer)
        url = reverse(
            "customer_portal:request-approve",
            kwargs={"pk": self.customer_request.pk},
        )

        first = self.client.post(url)
        second = self.client.post(url)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.customer_request.refresh_from_db()
        self.assertIsNotNone(self.customer_request.converted_order_id)
        self.assertEqual(
            AIEvent.objects.filter(
                event_type=EVENT_TYPE_ORDER_CREATED,
                source_id=str(self.customer_request.converted_order_id),
            ).count(),
            1,
        )
        self.assertEqual(
            AIRecommendation.objects.filter(
                category=CATEGORY_NEW_ORDER,
                source_id=str(self.customer_request.converted_order_id),
            ).count(),
            1,
        )
