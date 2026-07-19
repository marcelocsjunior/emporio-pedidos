from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import ROLE_ATTENDANCE, ensure_roles
from customer_portal.models import (
    CustomerDeliveryLocation,
    CustomerOrderRequest,
    CustomerOrderRequestItem,
)
from orders.models import AuditEvent, Company, Order, OrderItem, Product


class DashboardAssistantTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_roles()
        cls.company = Company.objects.create(name="Empresa Assistida", active=True)
        cls.product = Product.objects.create(
            name="Marmita executiva",
            unit_price=Decimal("25.00"),
        )
        cls.attendance = User.objects.create_user("atendente-ia", password="Senha!123456")
        cls.attendance.groups.add(Group.objects.get(name=ROLE_ATTENDANCE))
        cls.unprivileged = User.objects.create_user("sem-permissao-ia", password="Senha!123456")
        cls.customer = User.objects.create_user("cliente-ia", password="Senha!123456")
        cls.location = CustomerDeliveryLocation.objects.create(
            company=cls.company,
            label="Sede",
            address="Rua Operacional, 10",
            city="Itabirito",
        )
        fixed_now = timezone.make_aware(datetime(2026, 7, 18, 10, 0))
        cls.order = Order.objects.create(
            company=cls.company,
            order_date=fixed_now.date(),
            delivery_date=fixed_now.date(),
            delivery_time=(fixed_now + timedelta(minutes=45)).time(),
            status=Order.Status.PENDING,
            delivery_location=cls.location.full_address,
        )
        OrderItem.objects.create(
            order=cls.order,
            product=cls.product,
            quantity=2,
            unit_price=cls.product.unit_price,
        )
        cls.customer_request = CustomerOrderRequest.objects.create(
            creation_key="dashboard-assistant-request",
            company=cls.company,
            requested_by=cls.customer,
            delivery_date=fixed_now.date() + timedelta(days=1),
            delivery_time=fixed_now.time(),
            delivery_location=cls.location,
            delivery_address_snapshot=cls.location.full_address,
            status=CustomerOrderRequest.Status.SUBMITTED,
            submitted_at=fixed_now,
        )
        CustomerOrderRequestItem.objects.create(
            request=cls.customer_request,
            product=cls.product,
            quantity=3,
            unit_price=cls.product.unit_price,
        )

    def test_feature_flag_disabled_preserves_existing_dashboard(self):
        self.client.force_login(self.attendance)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Painel operacional")
        self.assertNotContains(response, "Assistente Operacional")

    @override_settings(AI_ASSISTANT_PANEL_ENABLED=True)
    @patch("intelligence.operational_assistant.timezone.now")
    def test_panel_shows_authorization_and_order_without_external_provider(self, now_mock):
        now_mock.return_value = timezone.make_aware(datetime(2026, 7, 18, 10, 0))
        self.client.force_login(self.attendance)

        with patch("intelligence.providers.GeminiProvider.generate") as generate:
            response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Assistente Operacional")
        self.assertContains(response, self.customer_request.protocol)
        self.assertContains(response, self.order.number)
        self.assertContains(response, "Copiar texto")
        generate.assert_not_called()

    @override_settings(AI_ASSISTANT_PANEL_ENABLED=True)
    def test_panel_failure_does_not_break_dashboard(self):
        self.client.force_login(self.attendance)
        with patch(
            "orders.assistant_views.build_operational_assistant",
            side_effect=RuntimeError("falha controlada"),
        ):
            response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "temporariamente indisponível")
        self.assertContains(response, "Pedidos por status")

    @override_settings(AI_ASSISTANT_PANEL_ENABLED=True)
    def test_user_without_permissions_does_not_receive_operational_data(self):
        self.client.force_login(self.unprivileged)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Assistente Operacional")
        self.assertNotContains(response, self.customer_request.protocol)
        self.assertNotContains(response, self.order.number)

    @override_settings(AI_ASSISTANT_PANEL_ENABLED=True)
    @patch("intelligence.operational_assistant.timezone.now")
    def test_dashboard_read_does_not_create_audit_or_change_status(self, now_mock):
        now_mock.return_value = timezone.make_aware(datetime(2026, 7, 18, 10, 0))
        self.client.force_login(self.attendance)
        audit_count = AuditEvent.objects.count()
        request_status = self.customer_request.status
        order_status = self.order.status

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.customer_request.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(AuditEvent.objects.count(), audit_count)
        self.assertEqual(self.customer_request.status, request_status)
        self.assertEqual(self.order.status, order_status)
