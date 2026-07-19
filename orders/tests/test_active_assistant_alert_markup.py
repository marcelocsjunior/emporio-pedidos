from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import ROLE_ATTENDANCE, ensure_roles
from intelligence.active_assistant import notify_order_created
from intelligence.models import AIRecommendation
from orders.models import Company, Order, OrderItem, Product


@override_settings(
    AI_ASSISTANT_PANEL_ENABLED=True,
    AI_ACTIVE_ASSISTANT_ENABLED=True,
    AI_ACTIVE_ASSISTANT_PROMPT_VERSION="mvp-ia-03-1-alert-test",
    AI_MODE="pilot",
)
class ActiveAssistantAlertMarkupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_roles()
        cls.operator = User.objects.create_user("operador-alerta")
        cls.operator.groups.add(Group.objects.get(name=ROLE_ATTENDANCE))
        cls.company = Company.objects.create(name="Empresa Alerta", active=True)
        cls.product = Product.objects.create(
            name="Refeição alerta",
            unit_price=Decimal("31.00"),
        )

    def setUp(self):
        self.order = Order.objects.create(
            company=self.company,
            delivery_date=timezone.localdate(),
            delivery_time=(timezone.localtime() + timedelta(hours=2)).time(),
            delivery_location="Portaria alerta",
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            unit_price=self.product.unit_price,
        )
        self.order.refresh_from_db()
        notify_order_created(self.order)
        self.recommendation = AIRecommendation.objects.get(source_id=str(self.order.pk))
        self.client.force_login(self.operator)

    def test_dashboard_exposes_interactive_alert_contract(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="assistant-new-order-badge"')
        self.assertContains(response, 'id="assistant-new-order-badge-count">1</strong>')
        self.assertContains(response, 'id="assistant-sound-toggle"')
        self.assertContains(response, 'id="assistant-live-alert"')
        self.assertContains(response, 'aria-live="assertive"')
        self.assertContains(
            response,
            f'data-active-notification-id="{self.recommendation.pk}"',
        )
        self.assertContains(
            response,
            f'data-order-url="{reverse("order-detail", args=[self.order.pk])}"',
        )
        self.assertContains(
            response,
            f'data-view-url="{reverse("assistant-recommendation-viewed", args=[self.recommendation.pk])}"',
        )
        self.assertContains(response, "emporioAssistantSoundEnabled")

    def test_partial_refresh_exposes_new_order_metadata_without_provider_call(self):
        response = self.client.get(reverse("assistant-updates"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-active-new-count="1"')
        self.assertContains(
            response,
            f'data-active-notification-id="{self.recommendation.pk}"',
        )
        self.assertContains(response, f'data-reference="{self.order.number}"')
        self.assertContains(response, 'data-company="Empresa Alerta"')

    @override_settings(AI_ACTIVE_ASSISTANT_ENABLED=False)
    def test_disabled_flag_hides_interactive_alert_controls(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="assistant-new-order-badge"')
        self.assertNotContains(response, 'id="assistant-sound-toggle"')
        self.assertNotContains(response, 'id="assistant-live-alert"')
