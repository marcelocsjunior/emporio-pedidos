from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import ROLE_ATTENDANCE, ROLE_PRODUCTION, ensure_roles
from orders.models import AuditEvent, Company, Order, OrderItem, Product


class Mvp03OperationalFlowTests(TestCase):
    def setUp(self):
        ensure_roles()
        self.attendance = User.objects.create_user(
            "mvp03-atendimento", password="Senha!123456"
        )
        self.attendance.groups.add(Group.objects.get(name=ROLE_ATTENDANCE))
        self.production = User.objects.create_user("mvp03-producao", password="Senha!123456")
        self.production.groups.add(Group.objects.get(name=ROLE_PRODUCTION))
        self.company = Company.objects.create(name="Empresa Operacional", active=True)
        self.product_a = Product.objects.create(
            name="Marmita completa MVP03",
            category="Refeição",
            unit_price=Decimal("20.00"),
            active=True,
        )
        self.product_b = Product.objects.create(
            name="Lanche MVP03",
            category="Lanche",
            unit_price=Decimal("12.50"),
            active=True,
        )
        self.client.force_login(self.attendance)

    def _set_creation_key(self, key: str) -> None:
        session = self.client.session
        session["emporio_order_creation_key"] = key
        session.save()

    def _order_payload(self, key: str) -> dict[str, str]:
        today = timezone.localdate().isoformat()
        return {
            "creation_key": key,
            "company": str(self.company.pk),
            "order_date": today,
            "delivery_date": today,
            "delivery_time": "12:00",
            "delivery_location": "Portaria principal",
            "notes": "Pedido de homologação",
            "items-TOTAL_FORMS": "2",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "1",
            "items-MAX_NUM_FORMS": "50",
            "items-0-product": str(self.product_a.pk),
            "items-0-quantity": "2",
            "items-1-product": str(self.product_b.pk),
            "items-1-quantity": "3",
        }

    def test_attendance_can_create_update_and_soft_deactivate_catalog_records(self):
        self.assertTrue(self.attendance.has_perm("orders.add_product"))
        company_response = self.client.post(
            reverse("company-create"),
            {
                "name": "Nova Empresa MVP03",
                "responsible_name": "Responsável",
                "phone": "31999990000",
                "address": "Rua de Teste, 10",
                "city": "Itabirito",
                "customer_type": Company.CustomerType.MONTHLY,
                "payment_terms": "Mensal",
                "notes": "",
            },
        )
        self.assertRedirects(company_response, reverse("company-list"))
        created_company = Company.objects.get(name="Nova Empresa MVP03")
        self.assertTrue(
            AuditEvent.objects.filter(
                action="company.created", entity_id=str(created_company.pk)
            ).exists()
        )

        product_response = self.client.post(
            reverse("product-create"),
            {"name": "Café MVP03", "category": "Café", "unit_price": "15.00"},
        )
        self.assertRedirects(product_response, reverse("product-list"))
        product = Product.objects.get(name="Café MVP03")

        toggle_response = self.client.post(reverse("product-toggle-active", args=[product.pk]))
        self.assertRedirects(toggle_response, reverse("product-list"))
        product.refresh_from_db()
        self.assertFalse(product.active)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="product.deactivated", entity_id=str(product.pk)
            ).exists()
        )

    def test_order_creation_is_atomic_calculated_audited_and_idempotent(self):
        key = "a" * 32
        self._set_creation_key(key)
        payload = self._order_payload(key)

        response = self.client.post(reverse("order-create"), payload)
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(creation_key=key)
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(order.total_amount, Decimal("77.50"))
        self.assertEqual(order.created_by, self.attendance)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertTrue(
            AuditEvent.objects.filter(action="order.created", entity_id=str(order.pk)).exists()
        )

        repeated = self.client.post(reverse("order-create"), payload)
        self.assertEqual(repeated.status_code, 302)
        self.assertEqual(Order.objects.filter(creation_key=key).count(), 1)
        self.assertEqual(
            AuditEvent.objects.filter(action="order.created", entity_id=str(order.pk)).count(),
            1,
        )

    def test_inactive_company_and_product_are_rejected_for_new_orders(self):
        inactive_company = Company.objects.create(name="Empresa Inativa MVP03", active=False)
        inactive_product = Product.objects.create(
            name="Produto Inativo MVP03",
            unit_price=Decimal("10.00"),
            active=False,
        )
        key = "b" * 32
        self._set_creation_key(key)
        payload = self._order_payload(key)
        payload["company"] = str(inactive_company.pk)
        payload["items-0-product"] = str(inactive_product.pk)

        response = self.client.post(reverse("order-create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Order.objects.filter(creation_key=key).exists())

    def test_editing_quantity_preserves_frozen_unit_price(self):
        order = Order.objects.create(
            company=self.company,
            order_date=timezone.localdate(),
            delivery_date=timezone.localdate(),
            delivery_location="Portaria",
            created_by=self.attendance,
            updated_by=self.attendance,
        )
        item = OrderItem.objects.create(
            order=order,
            product=self.product_a,
            quantity=1,
            unit_price=self.product_a.unit_price,
        )
        self.product_a.unit_price = Decimal("30.00")
        self.product_a.save(update_fields=("unit_price", "updated_at"))

        response = self.client.post(
            reverse("order-update", args=[order.pk]),
            {
                "company": str(self.company.pk),
                "order_date": order.order_date.isoformat(),
                "delivery_date": order.delivery_date.isoformat(),
                "delivery_time": "12:30",
                "delivery_location": "Portaria atualizada",
                "notes": "",
                "items-TOTAL_FORMS": "1",
                "items-INITIAL_FORMS": "1",
                "items-MIN_NUM_FORMS": "1",
                "items-MAX_NUM_FORMS": "50",
                "items-0-id": str(item.pk),
                "items-0-product": str(self.product_a.pk),
                "items-0-quantity": "3",
            },
        )
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(item.unit_price, Decimal("20.00"))
        self.assertEqual(item.line_total, Decimal("60.00"))
        self.assertEqual(order.total_amount, Decimal("60.00"))
        self.assertTrue(
            AuditEvent.objects.filter(action="order.updated", entity_id=str(order.pk)).exists()
        )

    def test_production_profile_cannot_open_order_creation(self):
        self.client.force_login(self.production)
        response = self.client.get(reverse("order-create"))
        self.assertEqual(response.status_code, 403)
