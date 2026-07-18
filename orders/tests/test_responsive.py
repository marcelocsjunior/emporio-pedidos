from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import User
from accounts.roles import ROLE_ATTENDANCE, ensure_roles
from config.error_views import server_error
from orders.models import Company, Product


class ResponsiveAndObservabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_roles()
        cls.user = User.objects.create_user("mobile", password="Senha!123456")
        cls.user.groups.add(Group.objects.get(name=ROLE_ATTENDANCE))
        cls.company = Company.objects.create(name="Empresa Responsiva")
        cls.product = Product.objects.create(
            name="Marmita Teste",
            category="Refeição",
            unit_price=Decimal("20.00"),
        )

    def test_authenticated_layout_has_collapsible_mobile_navigation(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="mobile-menu"')
        self.assertContains(response, 'aria-label="Navegação móvel"')
        self.assertContains(response, "Alterar senha")

    def test_operational_tables_expose_mobile_labels(self):
        self.client.force_login(self.user)

        companies = self.client.get(reverse("company-list"))
        products = self.client.get(reverse("product-list"))

        self.assertContains(companies, 'class="responsive-table"')
        self.assertContains(companies, 'data-label="Empresa"')
        self.assertContains(products, 'class="responsive-table"')
        self.assertContains(products, 'data-label="Valor unitário"')

    def test_every_response_receives_request_id(self):
        response = self.client.get(reverse("healthcheck"), HTTP_X_REQUEST_ID="hml-check-001")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "hml-check-001")

    def test_server_error_page_exposes_correlation_code(self):
        request = RequestFactory().get("/falha-controlada/")
        request.request_id = "error-check-001"

        response = server_error(request)

        self.assertEqual(response.status_code, 500)
        self.assertIn(b"error-check-001", response.content)
        self.assertIn(b"C\xc3\xb3digo de rastreamento", response.content)
