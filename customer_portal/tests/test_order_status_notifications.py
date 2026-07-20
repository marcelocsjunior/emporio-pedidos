from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from customer_portal.models import CustomerPortalAccess
from customer_portal.order_notifications import (
    SOURCE_TYPE_ORDER_STATUS_HISTORY,
    VIEW_AUDIT_ACTION,
)
from intelligence.models import AIRecommendation
from orders.models import AuditEvent, Company, Order, OrderItem, Product
from orders.services import change_order_status


class CustomerOrderStatusNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Cliente Portal")
        cls.other_company = Company.objects.create(name="Outra Empresa")
        cls.customer = User.objects.create_user("cliente", password="Senha!123456")
        cls.second_customer = User.objects.create_user(
            "cliente-colega", password="Senha!123456"
        )
        cls.other_customer = User.objects.create_user(
            "cliente-outra", password="Senha!123456"
        )
        cls.operator = User.objects.create_user("operador", password="Senha!123456")
        CustomerPortalAccess.objects.create(user=cls.customer, company=cls.company)
        CustomerPortalAccess.objects.create(user=cls.second_customer, company=cls.company)
        CustomerPortalAccess.objects.create(
            user=cls.other_customer,
            company=cls.other_company,
        )
        cls.product = Product.objects.create(
            name="Refeição",
            unit_price=Decimal("25.00"),
        )

    def setUp(self):
        self.order = Order.objects.create(
            company=self.company,
            delivery_date=timezone.localdate() + timedelta(days=1),
            status=Order.Status.PENDING,
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            unit_price=self.product.unit_price,
        )

    def transition(self, new_status, key):
        with self.captureOnCommitCallbacks(execute=True):
            return change_order_status(
                order_id=self.order.pk,
                new_status=new_status,
                actor=self.operator,
                idempotency_key=key,
            )

    def notification(self):
        return AIRecommendation.objects.get(
            source_type=SOURCE_TYPE_ORDER_STATUS_HISTORY
        )

    def test_real_transition_creates_one_notification_with_correct_states(self):
        self.transition(Order.Status.RECEIVED, "cliente-transition-1")

        notification = self.notification()
        self.assertEqual(notification.evidence["from_status"], Order.Status.PENDING)
        self.assertEqual(notification.evidence["to_status"], Order.Status.RECEIVED)
        self.assertEqual(notification.evidence["company_id"], str(self.company.pk))
        self.assertEqual(notification.evidence["order_number"], self.order.number)

    def test_same_status_does_not_create_or_duplicate_notification(self):
        self.transition(Order.Status.RECEIVED, "cliente-transition-1")

        with self.assertRaises(ValidationError):
            self.transition(Order.Status.RECEIVED, "cliente-transition-same")

        self.assertEqual(
            AIRecommendation.objects.filter(
                source_type=SOURCE_TYPE_ORDER_STATUS_HISTORY
            ).count(),
            1,
        )

    def test_next_transition_creates_a_new_notification(self):
        self.transition(Order.Status.RECEIVED, "cliente-transition-1")
        self.transition(Order.Status.IN_PRODUCTION, "cliente-transition-2")

        notifications = AIRecommendation.objects.filter(
            source_type=SOURCE_TYPE_ORDER_STATUS_HISTORY
        )
        self.assertEqual(notifications.count(), 2)
        self.assertEqual(notifications.values("idempotency_key").distinct().count(), 2)

    def test_notification_failure_does_not_prevent_status_change(self):
        with patch(
            "customer_portal.order_notifications.create_order_status_notification",
            side_effect=RuntimeError("controlled failure"),
        ):
            self.transition(Order.Status.RECEIVED, "cliente-transition-failure")

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.RECEIVED)
        self.assertFalse(
            AIRecommendation.objects.filter(
                source_type=SOURCE_TYPE_ORDER_STATUS_HISTORY
            ).exists()
        )

    def test_owner_sees_polling_content_and_other_company_does_not(self):
        self.transition(Order.Status.RECEIVED, "cliente-transition-1")
        self.client.force_login(self.customer)

        response = self.client.get(reverse("customer_portal:order-notification-updates"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.number)
        self.assertContains(response, "Pendente")
        self.assertContains(response, "Recebido")
        self.assertContains(response, "Abrir pedido")
        self.assertContains(response, "Marcar como visto")
        self.assertContains(response, 'data-unseen-count="1"')

        self.client.force_login(self.other_customer)
        response = self.client.get(reverse("customer_portal:order-notification-updates"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.order.number)
        self.assertContains(response, 'data-unseen-count="0"')

    def test_unauthenticated_user_cannot_access_polling_or_order(self):
        polling = self.client.get(reverse("customer_portal:order-notification-updates"))
        detail = self.client.get(
            reverse("customer_portal:order-detail", kwargs={"pk": self.order.pk})
        )

        self.assertEqual(polling.status_code, 302)
        self.assertEqual(detail.status_code, 302)

    def test_order_detail_is_isolated_by_company(self):
        url = reverse("customer_portal:order-detail", kwargs={"pk": self.order.pk})
        self.client.force_login(self.customer)
        allowed = self.client.get(url)
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, self.order.number)

        self.client.force_login(self.other_customer)
        denied = self.client.get(url)
        self.assertEqual(denied.status_code, 404)

    def test_mark_viewed_is_idempotent_audited_once_and_updates_count(self):
        self.transition(Order.Status.RECEIVED, "cliente-transition-1")
        notification = self.notification()
        url = reverse(
            "customer_portal:order-notification-viewed",
            kwargs={"pk": notification.pk},
        )
        self.client.force_login(self.customer)

        first = self.client.post(url)
        second = self.client.post(url)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(
            AuditEvent.objects.filter(
                actor=self.customer,
                action=VIEW_AUDIT_ACTION,
                entity_id=str(notification.pk),
            ).count(),
            1,
        )
        polling = self.client.get(reverse("customer_portal:order-notification-updates"))
        self.assertContains(polling, 'data-unseen-count="0"')
        self.assertNotContains(polling, self.order.number)

        self.client.force_login(self.second_customer)
        colleague_polling = self.client.get(
            reverse("customer_portal:order-notification-updates")
        )
        self.assertContains(colleague_polling, 'data-unseen-count="1"')

    def test_other_company_cannot_mark_notification_viewed(self):
        self.transition(Order.Status.RECEIVED, "cliente-transition-1")
        notification = self.notification()
        self.client.force_login(self.other_customer)

        response = self.client.post(
            reverse(
                "customer_portal:order-notification-viewed",
                kwargs={"pk": notification.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            AuditEvent.objects.filter(
                actor=self.other_customer,
                action=VIEW_AUDIT_ACTION,
            ).exists()
        )

    def test_portal_interface_has_persistent_responsive_notification_markup(self):
        self.transition(Order.Status.RECEIVED, "cliente-transition-1")
        self.client.force_login(self.customer)

        response = self.client.get(reverse("customer_portal:request-list"))

        self.assertContains(response, 'id="portal-order-notifications"')
        self.assertContains(response, self.order.number)
        self.assertContains(response, "Estado anterior")
        self.assertContains(response, "Novo estado")
        self.assertContains(response, "customer_order_notifications.js")
        self.assertContains(response, "portal-order-sound-toggle")
        self.assertContains(response, 'aria-pressed="false"')
        self.assertContains(
            response,
            f'data-order-notification-id="{self.notification().pk}"',
        )
        self.assertContains(response, f'data-order-number="{self.order.number}"')
        self.assertContains(response, 'data-new-status="Recebido"')

    def test_portal_alert_javascript_exposes_local_deduplication_contract(self):
        script_path = (
            Path(__file__).parents[2] / "static/js/customer_order_notifications.js"
        )
        script = script_path.read_text(encoding="utf-8")

        self.assertIn("emporioCustomerOrderNotificationsSoundEnabled", script)
        self.assertIn("emporioCustomerOrderNotificationsAnnounced", script)
        self.assertIn("window.AudioContext || window.webkitAudioContext", script)
        self.assertIn("const unannounced = notifications.filter", script)
        self.assertIn('method: "POST"', script)
        self.assertIn('"X-CSRFToken": getCookie("csrftoken")', script)
        self.assertIn("portal-order-live-alert", script)
