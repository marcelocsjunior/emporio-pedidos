from django.test import TestCase
from django.urls import reverse

from accounts.models import User, UserCapabilityOverride
from accounts.roles import ROLE_ADMIN, ensure_roles
from customer_portal.models import CustomerPortalAccess
from orders.models import Company


class HeaderNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles = ensure_roles()
        cls.ti = User.objects.create_superuser(
            username="ti", email="ti@example.invalid", password="SenhaForte!2026"
        )
        cls.rafa = User.objects.create_user(username="rafa", password="SenhaForte!2026")
        cls.rafa.groups.add(roles[ROLE_ADMIN])
        UserCapabilityOverride.objects.create(
            user=cls.rafa, capability="manage_companies", effect="deny"
        )
        cls.bio = User.objects.create_user(username="bio", password="SenhaForte!2026")
        cls.customer = User.objects.create_user(username="cliente-menu", password="SenhaForte!2026")
        company = Company.objects.create(name="Cliente Menu")
        CustomerPortalAccess.objects.create(user=cls.customer, company=company)

    def setUp(self):
        for user in (self.ti, self.rafa, self.bio, self.customer):
            user.__dict__.pop("_capability_override_cache", None)

    def dashboard_for(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("dashboard"))

    def test_anonymous_layout_has_no_internal_navigation(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'aria-label="Navegação principal"')
        self.assertNotContains(response, 'aria-label="Administração"')
        self.assertNotContains(response, 'class="mobile-menu"')

    def test_ti_sees_operational_administration_and_account_menus(self):
        response = self.dashboard_for(self.ti)

        self.assertEqual(response.status_code, 200)
        for label in (
            "Painel",
            "Solicitações",
            "Pedidos",
            "Empresas",
            "Produtos",
            "Fechamentos",
            "Central Inteligente",
        ):
            self.assertContains(response, label)
        for route_name in (
            "customer_portal:access-list",
            "customer_portal:access-request-queue",
            "audit-list",
            "user-access-list",
            "technical-area",
        ):
            self.assertContains(response, reverse(route_name))
        self.assertContains(response, "Administração")
        self.assertContains(response, "Conta")
        self.assertContains(response, "Alterar senha")

    def test_each_administration_item_uses_its_existing_capability_condition(self):
        template = self._template_source()

        self.assertIn("{% if can_manage_companies %}", template)
        self.assertIn("{% if can_view_audit %}", template)
        self.assertIn("{% if can_manage_users or can_manage_attendants %}", template)
        self.assertIn("{% if can_access_technical_area %}", template)
        self.assertEqual(template.count("customer_portal:access-list"), 2)
        self.assertEqual(template.count("customer_portal:access-request-queue"), 2)

    def test_rafa_manage_companies_deny_hides_both_customer_access_items(self):
        response = self.dashboard_for(self.rafa)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("customer_portal:access-list"))
        self.assertNotContains(response, reverse("customer_portal:access-request-queue"))
        self.assertContains(response, reverse("audit-list"))
        self.assertContains(response, reverse("user-access-list"))

    def test_bio_receives_no_operational_or_administration_items(self):
        response = self.dashboard_for(self.bio)

        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'aria-label="Administração"', status_code=403)

    def test_customer_portal_header_remains_isolated_from_internal_administration(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("customer_portal:request-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Portal do cliente"')
        self.assertNotContains(response, 'aria-label="Administração"')
        self.assertNotContains(response, reverse("user-access-list"))
        self.assertNotContains(response, reverse("technical-area"))

    def test_account_logout_is_post_with_csrf(self):
        response = self.dashboard_for(self.ti)
        body = response.content.decode()
        logout_action = f'action="{reverse("logout")}"'

        self.assertEqual(body.count(f'<form method="post" {logout_action}>'), 2)
        self.assertGreaterEqual(body.count('name="csrfmiddlewaretoken"'), 2)
        self.assertNotIn(f'href="{reverse("logout")}"', body)

    def test_required_header_routes_are_reversible(self):
        for route_name in (
            "dashboard",
            "customer_portal:request-queue",
            "order-list",
            "company-list",
            "product-list",
            "closing-list",
            "intelligence:central",
            "customer_portal:access-list",
            "customer_portal:access-request-queue",
            "audit-list",
            "user-access-list",
            "technical-area",
            "password_change",
            "logout",
        ):
            with self.subTest(route=route_name):
                self.assertTrue(reverse(route_name).startswith("/"))

    @staticmethod
    def _template_source():
        with open("templates/base.html", encoding="utf-8") as source:
            return source.read()


class HeaderCssContractTests(TestCase):
    def test_compact_breakpoint_and_viewport_guards(self):
        with open("static/css/app.css", encoding="utf-8") as source:
            css = source.read()

        self.assertIn("@media (max-width: 1280px)", css)
        self.assertIn("max-width: min(320px, calc(100vw - 28px))", css)
        self.assertIn("max-height: calc(100vh - 88px)", css)
        self.assertIn("overflow-y: auto", css)
        self.assertIn(".topbar summary:focus-visible", css)
