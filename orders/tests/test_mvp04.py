from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.roles import ROLE_ATTENDANCE, ROLE_FINANCE, ensure_roles
from orders.closing_services import (
    build_whatsapp_link,
    change_closing_status,
    generate_or_recalculate_closing,
)
from orders.models import AuditEvent, Company, MonthlyClosing, Order, OrderItem, Product


class Mvp04ClosingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_roles()
        cls.finance = User.objects.create_user("financeiro-mvp04", password="Senha!123456")
        cls.finance.groups.add(Group.objects.get(name=ROLE_FINANCE))
        cls.attendance = User.objects.create_user("atendimento-mvp04", password="Senha!123456")
        cls.attendance.groups.add(Group.objects.get(name=ROLE_ATTENDANCE))

        cls.month = timezone.localdate().replace(day=1)
        cls.company = Company.objects.create(
            name="Empresa Fechamento",
            phone="(31) 99999-0000",
        )
        cls.product = Product.objects.create(
            name="Marmita fechamento",
            unit_price=Decimal("20.00"),
        )
        cls.delivered = Order.objects.create(
            company=cls.company,
            order_date=cls.month,
            delivery_date=cls.month,
            status=Order.Status.DELIVERED,
            delivery_location="Portaria",
        )
        OrderItem.objects.create(
            order=cls.delivered,
            product=cls.product,
            quantity=2,
            unit_price=Decimal("0.00"),
        )
        cls.pending = Order.objects.create(
            company=cls.company,
            order_date=cls.month,
            delivery_date=cls.month,
            status=Order.Status.PENDING,
            delivery_location="Recepção",
        )
        OrderItem.objects.create(
            order=cls.pending,
            product=cls.product,
            quantity=5,
            unit_price=Decimal("0.00"),
        )

    def _generate(self) -> MonthlyClosing:
        return generate_or_recalculate_closing(
            company_id=self.company.pk,
            reference_month=self.month,
            actor=self.finance,
        )

    def test_closing_counts_only_delivered_orders_and_builds_message(self):
        closing = self._generate()

        self.assertEqual(closing.order_count, 1)
        self.assertEqual(closing.item_count, 2)
        self.assertEqual(closing.total_amount, Decimal("40.00"))
        self.assertEqual(closing.status, MonthlyClosing.Status.TO_REVIEW)
        self.assertIn("Pedidos entregues: 1", closing.message_snapshot)
        self.assertIn("R$ 40,00", closing.message_snapshot)
        self.assertNotIn(self.pending.number, closing.message_snapshot)

    def test_generation_is_idempotent_and_recalculation_is_audited(self):
        first = self._generate()
        second = self._generate()

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            MonthlyClosing.objects.filter(
                company=self.company,
                reference_month=self.month,
            ).count(),
            1,
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                entity_id=str(first.pk),
                action="closing.recalculated",
            ).exists()
        )

    def test_status_flow_validates_then_invoices_and_blocks_recalculation(self):
        closing = self._generate()
        validated = change_closing_status(
            closing_id=closing.pk,
            new_status=MonthlyClosing.Status.VALIDATED,
            actor=self.finance,
            reason="Conferido",
        )
        self.assertIsNotNone(validated.validated_at)

        invoiced = change_closing_status(
            closing_id=closing.pk,
            new_status=MonthlyClosing.Status.INVOICED,
            actor=self.finance,
        )
        self.assertEqual(invoiced.status, MonthlyClosing.Status.INVOICED)
        self.assertIsNotNone(invoiced.invoiced_at)
        self.assertEqual(
            AuditEvent.objects.filter(
                entity_id=str(closing.pk),
                action="closing.status_changed",
            ).count(),
            2,
        )

        with self.assertRaises(ValidationError):
            self._generate()

    def test_empty_closing_cannot_be_validated(self):
        empty_company = Company.objects.create(name="Empresa sem entregas")
        closing = generate_or_recalculate_closing(
            company_id=empty_company.pk,
            reference_month=self.month,
            actor=self.finance,
        )

        with self.assertRaises(ValidationError):
            change_closing_status(
                closing_id=closing.pk,
                new_status=MonthlyClosing.Status.VALIDATED,
                actor=self.finance,
            )

    def test_whatsapp_link_is_manual_and_uses_company_phone(self):
        closing = self._generate()
        link = build_whatsapp_link(closing)

        self.assertTrue(link.startswith("https://wa.me/5531999990000?text="))
        self.assertIn("Pedidos%20entregues", link)

    def test_finance_gui_generates_details_and_exports_only_delivered_orders(self):
        self.client.force_login(self.finance)
        response = self.client.post(
            reverse("closing-generate"),
            {
                "company": str(self.company.pk),
                "reference_month": self.month.strftime("%Y-%m"),
            },
        )
        closing = MonthlyClosing.objects.get(company=self.company, reference_month=self.month)

        self.assertRedirects(response, reverse("closing-detail", kwargs={"pk": closing.pk}))
        detail = self.client.get(reverse("closing-detail", kwargs={"pk": closing.pk}))
        self.assertContains(detail, "Copiar mensagem")
        self.assertContains(detail, "não dispara mensagens automaticamente")
        self.assertContains(detail, self.delivered.number)
        self.assertNotContains(detail, self.pending.number)

        exported = self.client.get(reverse("closing-export-csv", kwargs={"pk": closing.pk}))
        csv_text = exported.content.decode("utf-8-sig")
        self.assertEqual(exported.status_code, 200)
        self.assertIn(self.delivered.number, csv_text)
        self.assertNotIn(self.pending.number, csv_text)
        self.assertIn("40,00", csv_text)

    def test_attendance_can_view_but_cannot_generate_or_change_closing(self):
        closing = self._generate()
        self.client.force_login(self.attendance)

        self.assertEqual(self.client.get(reverse("closing-list")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("closing-detail", kwargs={"pk": closing.pk})).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                reverse("closing-generate"),
                {
                    "company": str(self.company.pk),
                    "reference_month": self.month.strftime("%Y-%m"),
                },
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("closing-status-update", kwargs={"pk": closing.pk}),
                {"new_status": MonthlyClosing.Status.VALIDATED},
            ).status_code,
            403,
        )

    def test_invalid_list_filters_do_not_break_the_gui(self):
        self.client.force_login(self.finance)
        response = self.client.get(
            reverse("closing-list"),
            {"company": "not-a-uuid", "reference_month": "invalid"},
        )
        self.assertEqual(response.status_code, 200)
