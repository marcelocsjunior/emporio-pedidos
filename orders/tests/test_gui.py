from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import (
    ROLE_ATTENDANCE,
    ROLE_FINANCE,
    ROLE_PRODUCTION,
    ensure_roles,
)
from orders.models import AuditEvent, Company, Order, OrderStatusHistory, Product


class OperationalGuiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_roles()
        cls.company = Company.objects.create(name="Empresa Teste", active=True)
        cls.product = Product.objects.create(
            name="Marmita completa",
            category="Refeição",
            unit_price=Decimal("22.00"),
        )
        cls.order = Order.objects.create(
            company=cls.company,
            order_date=timezone.localdate(),
            delivery_date=timezone.localdate() + timedelta(days=1),
            status=Order.Status.PENDING,
            delivery_location="Portaria",
        )

        cls.attendance = User.objects.create_user("atendimento", password="Senha!123456")
        cls.attendance.groups.add(Group.objects.get(name=ROLE_ATTENDANCE))
        cls.production = User.objects.create_user("producao", password="Senha!123456")
        cls.production.groups.add(Group.objects.get(name=ROLE_PRODUCTION))
        cls.finance = User.objects.create_user("financeiro", password="Senha!123456")
        cls.finance.groups.add(Group.objects.get(name=ROLE_FINANCE))
        cls.unprivileged = User.objects.create_user("semperfil", password="Senha!123456")

    def test_dashboard_and_operational_lists_respect_permissions(self):
        self.client.force_login(self.attendance)
        dashboard = self.client.get(reverse("dashboard"))
        companies = self.client.get(reverse("company-list"))
        orders = self.client.get(reverse("order-list"))

        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Painel operacional")
        self.assertEqual(companies.status_code, 200)
        self.assertContains(companies, self.company.name)
        self.assertEqual(orders.status_code, 200)
        self.assertContains(orders, self.order.number)

        self.client.force_login(self.unprivileged)
        denied = self.client.get(reverse("order-list"))
        self.assertEqual(denied.status_code, 403)

    def test_role_based_status_flow_records_history_and_audit(self):
        self.client.force_login(self.attendance)
        response = self.client.post(
            reverse("order-status-update", kwargs={"pk": self.order.pk}),
            {"new_status": Order.Status.RECEIVED},
        )
        self.assertRedirects(
            response,
            reverse("order-detail", kwargs={"pk": self.order.pk}),
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.RECEIVED)

        self.client.force_login(self.production)
        response = self.client.post(
            reverse("order-status-update", kwargs={"pk": self.order.pk}),
            {"new_status": Order.Status.IN_PRODUCTION},
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.IN_PRODUCTION)
        self.assertEqual(OrderStatusHistory.objects.filter(order=self.order).count(), 2)
        self.assertEqual(
            AuditEvent.objects.filter(
                entity_id=str(self.order.pk), action="order.status_changed"
            ).count(),
            2,
        )

    def test_finance_cannot_change_operational_status(self):
        self.client.force_login(self.finance)
        response = self.client.post(
            reverse("order-status-update", kwargs={"pk": self.order.pk}),
            {"new_status": Order.Status.RECEIVED},
        )

        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)
