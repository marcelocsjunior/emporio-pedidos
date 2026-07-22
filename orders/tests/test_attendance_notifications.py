from datetime import time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.access import ROLE_CAPABILITIES, Capability
from accounts.roles import (
    OFFICIAL_ROLE_NAMES,
    ROLE_ADMIN,
    ROLE_ATTENDANCE,
    ROLE_COMMERCIAL,
    ROLE_MANAGEMENT,
    ROLE_OFFICIAL_SUPPORT,
    ROLE_OPERATIONAL,
    ROLE_STOCK,
    ensure_roles,
)
from customer_portal.models import CustomerDeliveryLocation, CustomerOrderRequest
from orders.models import Company, Order

User = get_user_model()


class OperationalRoleMatrixTests(TestCase):
    def test_official_matrix_is_exact_and_idempotent(self):
        legacy = ensure_roles()
        first_ids = {name: legacy[name].pk for name in legacy}
        second = ensure_roles()
        self.assertEqual(first_ids, {name: second[name].pk for name in second})
        self.assertEqual(len(OFFICIAL_ROLE_NAMES), 7)
        self.assertEqual(
            ROLE_CAPABILITIES[ROLE_MANAGEMENT],
            frozenset(
                {
                    Capability.ACCESS_DASHBOARD, Capability.VIEW_COMPANIES,
                    Capability.MANAGE_COMPANIES, Capability.VIEW_ORDERS,
                    Capability.CREATE_ORDERS, Capability.EDIT_ORDERS,
                    Capability.CHANGE_ORDER_STATUS, Capability.CANCEL_ORDERS,
                    Capability.VIEW_REQUESTS, Capability.APPROVE_REQUESTS,
                    Capability.REJECT_REQUESTS, Capability.REQUEST_CORRECTION,
                    Capability.VIEW_PRODUCTS, Capability.MANAGE_PRODUCTS,
                    Capability.VIEW_CLOSINGS, Capability.REVIEW_CLOSINGS,
                    Capability.EXPORT_CLOSINGS, Capability.VIEW_REPORTS,
                    Capability.VIEW_AUDIT, Capability.ACCESS_INTELLIGENCE,
                    Capability.RECORD_AI_FEEDBACK,
                }
            ),
        )
        self.assertNotIn(Capability.MANAGE_ATTENDANTS, ROLE_CAPABILITIES[ROLE_MANAGEMENT])
        self.assertEqual(
            ROLE_CAPABILITIES[ROLE_ATTENDANCE],
            frozenset(
                {
                    Capability.ACCESS_DASHBOARD, Capability.VIEW_ORDERS,
                    Capability.CREATE_ORDERS, Capability.EDIT_ORDERS,
                    Capability.CHANGE_ORDER_STATUS, Capability.VIEW_REQUESTS,
                    Capability.REQUEST_CORRECTION, Capability.VIEW_COMPANIES,
                    Capability.VIEW_PRODUCTS,
                }
            ),
        )
        self.assertEqual(
            ROLE_CAPABILITIES[ROLE_OPERATIONAL],
            frozenset({Capability.ACCESS_DASHBOARD, Capability.VIEW_ORDERS,
                       Capability.EDIT_ORDERS, Capability.CHANGE_ORDER_STATUS,
                       Capability.VIEW_REQUESTS, Capability.VIEW_PRODUCTS}),
        )
        self.assertEqual(
            ROLE_CAPABILITIES[ROLE_STOCK],
            frozenset({Capability.ACCESS_DASHBOARD, Capability.VIEW_PRODUCTS,
                       Capability.MANAGE_PRODUCTS, Capability.VIEW_ORDERS}),
        )
        self.assertFalse(ROLE_CAPABILITIES[ROLE_OFFICIAL_SUPPORT] & {
            Capability.CREATE_ORDERS, Capability.EDIT_ORDERS,
            Capability.CHANGE_ORDER_STATUS, Capability.MANAGE_COMPANIES,
            Capability.MANAGE_PRODUCTS,
        })
        self.assertIn(Capability.APPROVE_REQUESTS, ROLE_CAPABILITIES[ROLE_COMMERCIAL])
        self.assertNotIn(Capability.CHANGE_ORDER_STATUS, ROLE_CAPABILITIES[ROLE_COMMERCIAL])
        self.assertIn(Capability.MANAGE_ATTENDANTS, ROLE_CAPABILITIES[ROLE_ADMIN])

    def test_profiles_do_not_change_user_flags_or_membership(self):
        roles = ensure_roles()
        user = User.objects.create_user(username="matrix-existing", password="safe-password")
        user.groups.add(roles[ROLE_STOCK])
        before = (user.password, user.is_staff, user.is_superuser, user.groups.get().pk)
        ensure_roles()
        user.refresh_from_db()
        after = (user.password, user.is_staff, user.is_superuser, user.groups.get().pk)
        self.assertEqual(before, after)


class AttendanceNotificationEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles = ensure_roles()
        cls.attendant = User.objects.create_user(
            username="notify-attendance", password="safe-password"
        )
        cls.attendant.groups.add(roles[ROLE_ATTENDANCE])
        cls.commercial = User.objects.create_user(
            username="notify-commercial", password="safe-password"
        )
        cls.commercial.groups.add(roles[ROLE_COMMERCIAL])
        cls.support = User.objects.create_user(username="notify-support", password="safe-password")
        cls.support.groups.add(roles[ROLE_OFFICIAL_SUPPORT])
        cls.company = Company.objects.create(code="NOTIFY", name="Empresa técnica de notificações")
        cls.location = CustomerDeliveryLocation.objects.create(
            company=cls.company, label="Local técnico", address="Ambiente isolado"
        )
        now = timezone.localtime()
        cls.order = Order.objects.create(
            company=cls.company, delivery_date=now.date(), delivery_time=time(0, 1),
            created_by=cls.attendant,
        )
        cls.delivered = Order.objects.create(
            company=cls.company, delivery_date=now.date(), delivery_time=time(0, 1),
            status=Order.Status.DELIVERED, created_by=cls.attendant,
        )
        cls.cancelled = Order.objects.create(
            company=cls.company, delivery_date=now.date(), delivery_time=time(0, 1),
            status=Order.Status.CANCELLED, created_by=cls.attendant,
        )
        cls.customer_request = CustomerOrderRequest.objects.create(
            creation_key="notify-request", company=cls.company, requested_by=cls.attendant,
            delivery_date=now.date() + timedelta(days=1), delivery_location=cls.location,
            status=CustomerOrderRequest.Status.SUBMITTED, submitted_at=timezone.now(),
        )
        cls.url = reverse("attendance-notification-updates")

    def test_authentication_and_authorization(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.support)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_attendance_receives_stable_limited_order_request_and_delay_events(self):
        self.client.force_login(self.attendant)
        before = (Order.objects.count(), CustomerOrderRequest.objects.count())
        with CaptureQueriesContext(connection) as queries:
            first = self.client.get(self.url)
        second = self.client.get(self.url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(before, (Order.objects.count(), CustomerOrderRequest.objects.count()))
        payload = first.json()
        self.assertEqual(payload["limit"], 30)
        self.assertLessEqual(len(payload["events"]), 30)
        self.assertEqual(
            payload["events"],
            sorted(
                payload["events"],
                key=lambda item: (item["occurred_at"], item["id"]),
                reverse=True,
            ),
        )
        types = {item["type"] for item in payload["events"]}
        self.assertEqual(types, {"new_order", "new_request", "late_order"})
        late_ids = {
            item["id"].split(":")[1]
            for item in payload["events"]
            if item["type"] == "late_order"
        }
        self.assertIn(str(self.order.pk), late_ids)
        self.assertNotIn(str(self.delivered.pk), late_ids)
        self.assertNotIn(str(self.cancelled.pk), late_ids)
        self.assertTrue(all(item["url"].startswith("/") for item in payload["events"]))
        self.assertIn("no-cache", first.headers["Cache-Control"])
        self.assertLessEqual(len(queries), 12)
        self.assertFalse(
            any(
                query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for query in queries
            )
        )

    def test_commercial_receives_requests_but_not_operational_alerts(self):
        self.client.force_login(self.commercial)
        event_types = {item["type"] for item in self.client.get(self.url).json()["events"]}
        self.assertEqual(event_types, {"new_request"})

    def test_header_has_mobile_safe_controls_and_local_sound_semantics(self):
        self.client.force_login(self.attendant)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "data-notification-center")
        self.assertContains(response, "Ativar som")
        script = (settings.BASE_DIR / "static/js/attendance_notifications.js").read_text()
        self.assertIn("localStorage", script)
        self.assertIn("AudioContext", script)
        self.assertIn("window.setInterval(poll, 25000)", script)

    def test_rafa_equivalent_accesses_list_detail_bell_and_correction_only(self):
        self.client.force_login(self.attendant)
        queue = self.client.get(reverse("customer_portal:request-queue"))
        detail = self.client.get(
            reverse("customer_portal:request-review", args=(self.customer_request.pk,))
        )
        self.assertEqual(queue.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        detail_url = reverse(
            "customer_portal:request-review", args=(self.customer_request.pk,)
        )
        self.assertContains(queue, detail_url)
        self.assertContains(detail, "Solicitar correção")
        self.assertNotContains(detail, "Aprovar e criar pedido")
        self.assertNotContains(detail, "Rejeitar solicitação")

        bell = self.client.get(self.url).json()["events"]
        request_event = next(item for item in bell if item["type"] == "new_request")
        self.assertEqual(
            request_event["url"],
            reverse("customer_portal:request-review", args=(self.customer_request.pk,)),
        )
        self.assertEqual(
            self.client.post(
                reverse("customer_portal:request-approve", args=(self.customer_request.pk,))
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("customer_portal:request-reject", args=(self.customer_request.pk,)),
                {"reason": "Não autorizado"},
            ).status_code,
            403,
        )
        correction = self.client.post(
            reverse("customer_portal:request-correction", args=(self.customer_request.pk,)),
            {"reason": "Corrigir dados técnicos do teste"},
        )
        self.assertEqual(correction.status_code, 302)
        self.customer_request.refresh_from_db()
        self.assertEqual(
            self.customer_request.status,
            CustomerOrderRequest.Status.CORRECTION_REQUESTED,
        )
