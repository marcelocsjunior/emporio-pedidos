from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from customer_portal.models import (
    CustomerDeliveryLocation,
    CustomerOrderRequest,
    CustomerOrderRequestItem,
    CustomerPortalAccess,
)
from intelligence.models import AIEvent, AIRecommendation
from intelligence.request_alerts import (
    CATEGORY_NEW_REQUEST,
    EVENT_TYPE_REQUEST_SUBMITTED,
    SOURCE_TYPE_CUSTOMER_REQUEST,
)
from orders.models import AuditEvent, Company, Product


@override_settings(
    AI_ASSISTANT_PANEL_ENABLED=True,
    AI_ACTIVE_ASSISTANT_ENABLED=True,
    AI_MODE="pilot",
)
class RequestSubmissionAlertTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = User.objects.create_user("cliente-alerta-fila")
        cls.reviewer = User.objects.create_user("revisor-alerta-fila")
        permission = Permission.objects.get(
            codename="review_customerorderrequest",
            content_type__app_label="customer_portal",
        )
        cls.reviewer.user_permissions.add(permission)
        cls.company = Company.objects.create(name="Empresa Fila", active=True)
        cls.location = CustomerDeliveryLocation.objects.create(
            company=cls.company,
            label="Portaria",
            address="Endereço operacional",
            city="Itabirito",
        )
        cls.product = Product.objects.create(
            name="Refeição fila",
            unit_price=Decimal("32.00"),
        )
        CustomerPortalAccess.objects.create(
            user=cls.customer,
            company=cls.company,
            active=True,
        )

    def setUp(self):
        self.customer_request = CustomerOrderRequest.objects.create(
            creation_key="request-alert-queue-key",
            company=self.company,
            requested_by=self.customer,
            delivery_date=timezone.localdate() + timedelta(days=1),
            delivery_time=(timezone.localtime() + timedelta(hours=3)).time(),
            delivery_location=self.location,
            status=CustomerOrderRequest.Status.DRAFT,
        )
        CustomerOrderRequestItem.objects.create(
            request=self.customer_request,
            product=self.product,
            quantity=3,
            unit_price=self.product.unit_price,
        )
        self.customer_request.refresh_from_db()

    def _submit_from_portal(self):
        self.client.force_login(self.customer)
        return self.client.post(
            reverse(
                "customer_portal:request-submit",
                kwargs={"pk": self.customer_request.pk},
            )
        )

    def _recommendation(self):
        return AIRecommendation.objects.get(
            category=CATEGORY_NEW_REQUEST,
            source_type=SOURCE_TYPE_CUSTOMER_REQUEST,
            source_id=str(self.customer_request.pk),
        )

    def test_portal_submission_creates_one_immediate_persistent_alert(self):
        first = self._submit_from_portal()
        second = self._submit_from_portal()

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.customer_request.refresh_from_db()
        self.assertEqual(
            self.customer_request.status,
            CustomerOrderRequest.Status.SUBMITTED,
        )
        self.assertEqual(
            AIEvent.objects.filter(
                event_type=EVENT_TYPE_REQUEST_SUBMITTED,
                source_type=SOURCE_TYPE_CUSTOMER_REQUEST,
                source_id=str(self.customer_request.pk),
                status=AIEvent.Status.COMPLETED,
            ).count(),
            1,
        )
        self.assertEqual(
            AIRecommendation.objects.filter(
                category=CATEGORY_NEW_REQUEST,
                source_type=SOURCE_TYPE_CUSTOMER_REQUEST,
                source_id=str(self.customer_request.pk),
            ).count(),
            1,
        )

    def test_reviewer_sees_request_in_dashboard_and_refresh_contract(self):
        self._submit_from_portal()
        recommendation = self._recommendation()
        self.client.force_login(self.reviewer)

        dashboard = self.client.get(reverse("dashboard"))
        refresh = self.client.get(reverse("assistant-updates"))

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(refresh.status_code, 200)
        self.assertContains(dashboard, "Solicitações pendentes")
        self.assertContains(dashboard, "request_alerts.js")
        self.assertContains(refresh, 'data-active-request-count="1"')
        self.assertContains(
            refresh,
            f'data-request-notification-id="{recommendation.pk}"',
        )
        self.assertContains(refresh, self.customer_request.protocol)
        self.assertContains(refresh, "Abrir solicitação")

    def test_mark_request_alert_viewed_is_idempotent_and_audited_once(self):
        self._submit_from_portal()
        recommendation = self._recommendation()
        self.client.force_login(self.reviewer)
        url = reverse(
            "assistant-recommendation-viewed",
            kwargs={"pk": recommendation.pk},
        )

        first = self.client.post(url)
        second = self.client.post(url)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        recommendation.refresh_from_db()
        self.assertEqual(recommendation.status, AIRecommendation.Status.VIEWED)
        self.assertEqual(
            AuditEvent.objects.filter(
                action="assistant.request_notification_viewed"
            ).count(),
            1,
        )

    def test_human_decision_removes_request_from_active_alert_panel(self):
        self._submit_from_portal()
        self.client.force_login(self.reviewer)
        CustomerOrderRequest.objects.filter(pk=self.customer_request.pk).update(
            status=CustomerOrderRequest.Status.APPROVED,
            approved_at=timezone.now(),
        )

        response = self.client.get(reverse("assistant-updates"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-active-request-count="0"')
        self.assertNotContains(response, self.customer_request.protocol)

    def test_user_without_review_permission_cannot_access_request_alert(self):
        self._submit_from_portal()
        recommendation = self._recommendation()
        self.client.force_login(self.customer)

        refresh = self.client.get(reverse("assistant-updates"))
        viewed = self.client.post(
            reverse(
                "assistant-recommendation-viewed",
                kwargs={"pk": recommendation.pk},
            )
        )

        self.assertEqual(refresh.status_code, 403)
        self.assertEqual(viewed.status_code, 403)
