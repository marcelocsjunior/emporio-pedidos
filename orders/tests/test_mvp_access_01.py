from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.roles import ROLE_ADMIN, ROLE_ATTENDANCE, ensure_roles
from orders.models import AuditEvent, Company, Order, OrderItem, Product
from orders.services import change_order_status

User = get_user_model()


class OrderAccessMVPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles = ensure_roles()
        cls.director = User.objects.create_user(
            username="director-order", password="safe-test-1"
        )
        cls.director.groups.add(roles[ROLE_ADMIN])
        cls.attendant = User.objects.create_user(
            username="attendant-order", password="safe-test-1"
        )
        cls.attendant.groups.add(roles[ROLE_ATTENDANCE])
        cls.company = Company.objects.create(name="Cliente de teste")
        cls.product = Product.objects.create(name="Produto de teste", unit_price=Decimal("10.00"))

    def make_order(self):
        order = Order.objects.create(
            company=self.company,
            delivery_date=timezone.localdate() + timedelta(days=1),
            created_by=self.director,
            updated_by=self.director,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=1,
            unit_price=self.product.unit_price,
        )
        order.recalculate_total()
        return order

    def test_cancel_requires_reason_in_service(self):
        order = self.make_order()
        with self.assertRaises(ValidationError):
            change_order_status(
                order_id=order.pk,
                new_status=Order.Status.CANCELLED,
                actor=self.director,
            )
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)

    def test_director_cancels_with_reason_and_attendant_is_denied(self):
        for actor in (self.director,):
            order = self.make_order()
            self.client.force_login(actor)
            response = self.client.post(
                reverse("order-status-update", args=(order.pk,)),
                {
                    "new_status": Order.Status.CANCELLED,
                    "reason": "Solicitação operacional",
                },
            )
            self.assertRedirects(response, reverse("order-detail", args=(order.pk,)))
            order.refresh_from_db()
            self.assertEqual(order.status, Order.Status.CANCELLED)
            self.assertTrue(
                AuditEvent.objects.filter(
                    action="order.status_changed",
                    entity_id=str(order.pk),
                    payload__reason="Solicitação operacional",
                ).exists()
            )
        denied_order = self.make_order()
        self.client.force_login(self.attendant)
        denied = self.client.post(
            reverse("order-status-update", args=(denied_order.pk,)),
            {"new_status": Order.Status.CANCELLED, "reason": "Tentativa sem privilégio"},
        )
        self.assertEqual(denied.status_code, 403)

    def test_attendant_can_edit_order_by_direct_url(self):
        order = self.make_order()
        self.client.force_login(self.attendant)
        response = self.client.get(reverse("order-update", args=(order.pk,)))
        self.assertEqual(response.status_code, 200)

        detail = self.client.get(reverse("order-detail", args=(order.pk,)))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, reverse("order-update", args=(order.pk,)))

    def test_attendant_can_change_structural_data_with_approved_edit_capability(self):
        order = self.make_order()
        other_company = Company.objects.create(name="Outro cliente de teste")
        other_product = Product.objects.create(
            name="Outro produto de teste", unit_price=Decimal("99.00")
        )
        item = order.items.get()
        self.client.force_login(self.attendant)
        response = self.client.post(
            reverse("order-update", args=(order.pk,)),
            {
                "company": str(other_company.pk),
                "order_date": (timezone.localdate() + timedelta(days=10)).isoformat(),
                "delivery_date": (timezone.localdate() + timedelta(days=20)).isoformat(),
                "delivery_time": "23:59",
                "delivery_location": "Local manipulado",
                "notes": "Condição comercial manipulada",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "1",
                "items-MIN_NUM_FORMS": "1",
                "items-MAX_NUM_FORMS": "50",
                "items-0-id": str(item.pk),
                "items-0-product": str(other_product.pk),
                "items-0-quantity": "999",
            },
        )

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(order.company_id, other_company.pk)
        self.assertEqual(order.delivery_location, "Local manipulado")
        self.assertEqual(item.product_id, other_product.pk)
        self.assertEqual(item.quantity, 999)
        self.assertTrue(
            AuditEvent.objects.filter(action="order.updated", entity_id=str(order.pk)).exists()
        )

    def test_cancel_without_reason_is_rejected_by_http_endpoint(self):
        order = self.make_order()
        self.client.force_login(self.attendant)
        response = self.client.post(
            reverse("order-status-update", args=(order.pk,)),
            {"new_status": Order.Status.CANCELLED},
        )
        self.assertEqual(response.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertFalse(
            AuditEvent.objects.filter(
                action="order.status_changed", entity_id=str(order.pk)
            ).exists()
        )
