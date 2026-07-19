from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import ROLE_ATTENDANCE, ensure_roles
from intelligence.active_assistant import notify_order_created
from intelligence.models import AIRecommendation
from orders.models import AuditEvent, Company, Order, OrderItem, Product


@override_settings(
    AI_ASSISTANT_PANEL_ENABLED=True,
    AI_ACTIVE_ASSISTANT_ENABLED=True,
    AI_ACTIVE_ASSISTANT_PROMPT_VERSION="mvp-ia-03-dashboard-test",
    AI_MODE="pilot",
)
class ActiveAssistantDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_roles()
        cls.attendance = User.objects.create_user(
            "atendente-ativo",
            password="Senha!123456",
        )
        cls.attendance.groups.add(Group.objects.get(name=ROLE_ATTENDANCE))
        cls.unprivileged = User.objects.create_user(
            "sem-acesso-ativo",
            password="Senha!123456",
        )
        cls.company = Company.objects.create(name="Empresa Piloto", active=True)
        cls.product = Product.objects.create(
            name="Refeição piloto",
            unit_price=Decimal("30.00"),
        )

    def setUp(self):
        self.order = Order.objects.create(
            company=self.company,
            delivery_date=timezone.localdate(),
            delivery_time=(timezone.localtime() + timedelta(hours=2)).time(),
            delivery_location="Local piloto",
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

    def _set_creation_key(self, key: str) -> None:
        session = self.client.session
        session["emporio_order_creation_key"] = key
        session.save()

    def test_dashboard_prioritizes_new_order_without_duplicate_card(self):
        self.client.force_login(self.attendance)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Novo pedido")
        self.assertContains(response, self.order.number)
        self.assertContains(response, "analisando o pedido em segundo plano")
        source_keys = {card.source_key for card in response.context["assistant_panel"].cards}
        self.assertNotIn(f"order:{self.order.pk}", source_keys)
        self.assertEqual(response.context["active_notification_panel"].new_count, 1)

    def test_partial_refresh_does_not_call_provider_or_write_audit(self):
        self.client.force_login(self.attendance)
        audit_count = AuditEvent.objects.count()

        with patch("intelligence.active_assistant.ActiveOrderGeminiProvider.generate") as generate:
            response = self.client.get(reverse("assistant-updates"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.number)
        self.assertEqual(AuditEvent.objects.count(), audit_count)
        generate.assert_not_called()

    def test_mark_as_viewed_is_idempotent_and_audited_once(self):
        self.client.force_login(self.attendance)
        url = reverse(
            "assistant-recommendation-viewed",
            kwargs={"pk": self.recommendation.pk},
        )

        first = self.client.post(url)
        second = self.client.post(url)

        self.assertRedirects(first, reverse("dashboard"))
        self.assertRedirects(second, reverse("dashboard"))
        self.recommendation.refresh_from_db()
        self.assertEqual(self.recommendation.status, AIRecommendation.Status.VIEWED)
        self.assertEqual(
            AuditEvent.objects.filter(action="assistant.notification_viewed").count(),
            1,
        )

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["active_notification_panel"].new_count, 0)
        source_keys = {card.source_key for card in response.context["assistant_panel"].cards}
        self.assertIn(f"order:{self.order.pk}", source_keys)

    def test_user_without_order_permission_cannot_access_internal_endpoints(self):
        self.client.force_login(self.unprivileged)

        refresh = self.client.get(reverse("assistant-updates"))
        viewed = self.client.post(
            reverse(
                "assistant-recommendation-viewed",
                kwargs={"pk": self.recommendation.pk},
            )
        )

        self.assertEqual(refresh.status_code, 403)
        self.assertEqual(viewed.status_code, 403)

    @override_settings(AI_ACTIVE_ASSISTANT_ENABLED=False)
    def test_active_flag_disabled_prevents_new_notification(self):
        other_order = Order.objects.create(
            company=self.company,
            delivery_date=timezone.localdate(),
            delivery_location="Local piloto",
        )
        OrderItem.objects.create(
            order=other_order,
            product=self.product,
            quantity=1,
            unit_price=self.product.unit_price,
        )

        created = notify_order_created(other_order)

        self.assertFalse(created)
        self.assertFalse(
            AIRecommendation.objects.filter(source_id=str(other_order.pk)).exists()
        )

    def test_internal_order_creation_route_creates_one_notification(self):
        self.client.force_login(self.attendance)
        key = "c" * 32
        self._set_creation_key(key)
        today = timezone.localdate().isoformat()
        payload = {
            "creation_key": key,
            "company": str(self.company.pk),
            "order_date": today,
            "delivery_date": today,
            "delivery_time": "14:00",
            "delivery_location": "Portaria piloto",
            "notes": "",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "50",
            "items-0-product": str(self.product.pk),
            "items-0-quantity": "3",
        }

        first = self.client.post(reverse("order-create"), payload)
        second = self.client.post(reverse("order-create"), payload)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        created_order = Order.objects.get(creation_key=key)
        self.assertEqual(
            AIRecommendation.objects.filter(source_id=str(created_order.pk)).count(),
            1,
        )
