from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.access import Capability, user_has_capability
from accounts.models import UserCapabilityOverride
from accounts.roles import (
    ROLE_ADMIN,
    ROLE_ATTENDANCE,
    ROLE_FINANCE,
    ROLE_SYSTEM_ADMIN,
    ensure_roles,
)
from orders.models import AuditEvent, Company, MonthlyClosing

User = get_user_model()


class IndividualCapabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles = ensure_roles()
        cls.root = User.objects.create_user(
            username="ti", password="safe-root-password", is_staff=True, is_superuser=True
        )
        cls.attendant = User.objects.create_user(
            username="rafa-capabilities", password="safe-attendant-password"
        )
        cls.attendant.groups.add(roles[ROLE_ATTENDANCE])
        cls.finance = User.objects.create_user(
            username="finance-capabilities", password="safe-finance-password"
        )
        cls.finance.groups.add(roles[ROLE_FINANCE])
        cls.director = User.objects.create_user(
            username="director-capabilities", password="safe-director-password"
        )
        cls.director.groups.add(roles[ROLE_ADMIN])
        cls.system_admin = User.objects.create_user(
            username="system-capabilities", password="safe-system-password"
        )
        cls.system_admin.groups.add(roles[ROLE_SYSTEM_ADMIN])
        cls.company = Company.objects.create(name="Empresa capabilities")
        cls.closing = MonthlyClosing.objects.create(
            company=cls.company,
            reference_month="2026-07-01",
            generated_by=cls.finance,
        )

    def setUp(self):
        for user in (self.attendant, self.finance, self.director, self.system_admin):
            user.__dict__.pop("_capability_override_cache", None)

    def test_dashboard_hides_closings_without_capability(self):
        self.client.force_login(self.attendant)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Fechamentos pendentes")
        self.assertNotContains(response, "produção e fechamentos")
        self.assertNotContains(response, reverse("closing-list"))
        self.assertEqual(self.client.get(reverse("closing-list")).status_code, 403)

    def test_dashboard_shows_closings_for_default_authorized_users(self):
        for user in (self.finance, self.director, self.root):
            with self.subTest(username=user.username):
                self.client.force_login(user)

                response = self.client.get(reverse("dashboard"))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Fechamentos pendentes")
                self.assertContains(response, "produção e fechamentos")

    def test_dashboard_follows_individual_closing_overrides(self):
        UserCapabilityOverride.objects.create(
            user=self.attendant,
            capability=Capability.VIEW_CLOSINGS,
            effect=UserCapabilityOverride.Effect.ALLOW,
        )
        UserCapabilityOverride.objects.create(
            user=self.finance,
            capability=Capability.VIEW_CLOSINGS,
            effect=UserCapabilityOverride.Effect.DENY,
        )

        self.client.force_login(self.attendant)
        allowed_response = self.client.get(reverse("dashboard"))
        self.assertContains(allowed_response, "Fechamentos pendentes")
        self.assertContains(allowed_response, "produção e fechamentos")

        self.client.force_login(self.finance)
        denied_response = self.client.get(reverse("dashboard"))
        self.assertNotContains(denied_response, "Fechamentos pendentes")
        self.assertNotContains(denied_response, "produção e fechamentos")

    def test_user_without_override_keeps_profile_default(self):
        self.assertTrue(user_has_capability(self.attendant, Capability.VIEW_ORDERS))
        self.assertFalse(user_has_capability(self.attendant, Capability.VIEW_CLOSINGS))

    def test_allow_adds_and_deny_removes_capabilities(self):
        UserCapabilityOverride.objects.create(
            user=self.attendant,
            capability=Capability.VIEW_CLOSINGS,
            effect=UserCapabilityOverride.Effect.ALLOW,
        )
        self.assertTrue(user_has_capability(self.attendant, Capability.VIEW_CLOSINGS))
        self.attendant.capability_overrides.update(effect=UserCapabilityOverride.Effect.DENY)
        self.attendant.__dict__.pop("_capability_override_cache", None)
        self.assertFalse(user_has_capability(self.attendant, Capability.VIEW_CLOSINGS))

    def test_deny_wins_over_django_compatibility_permission(self):
        permission = Permission.objects.get(content_type__app_label="orders", codename="view_order")
        self.attendant.user_permissions.add(permission)
        UserCapabilityOverride.objects.create(
            user=self.attendant,
            capability=Capability.VIEW_ORDERS,
            effect=UserCapabilityOverride.Effect.DENY,
        )
        self.assertFalse(user_has_capability(self.attendant, Capability.VIEW_ORDERS))

    def test_root_override_and_unknown_capability_are_rejected(self):
        with self.assertRaises(ValidationError):
            UserCapabilityOverride.objects.create(
                user=self.root,
                capability=Capability.VIEW_ORDERS,
                effect=UserCapabilityOverride.Effect.DENY,
            )
        with self.assertRaises(ValidationError):
            UserCapabilityOverride.objects.create(
                user=self.attendant, capability="auth.change_permission", effect="allow"
            )

    def test_authorized_manager_sees_three_state_override_editor(self):
        update_url = reverse("user-access-update", args=(self.attendant.pk,))
        self.client.force_login(self.system_admin)
        page = self.client.get(update_url)
        self.assertContains(page, "Acessos individuais")
        self.assertContains(page, "Padrão do perfil")
        self.assertContains(page, "Permitido")
        self.assertContains(page, "Bloqueado")
        self.assertContains(page, "Herdado: permitido")
        self.assertContains(page, "Efetivo: permitido")
        response = self.client.post(
            update_url,
            {
                "username": self.attendant.username,
                "role": ROLE_ATTENDANCE,
                "capability_state__view_closings": "allow",
                "capability_state__create_orders": "deny",
            },
        )
        self.assertRedirects(response, reverse("user-access-list"))
        effects = dict(self.attendant.capability_overrides.values_list("capability", "effect"))
        self.assertEqual(effects[Capability.VIEW_CLOSINGS], "allow")
        self.assertEqual(effects[Capability.CREATE_ORDERS], "deny")

        self.client.force_login(self.root)
        self.assertContains(self.client.get(update_url), "Acessos individuais")

    def test_root_atomically_replaces_deltas_and_restores_profile(self):
        update_url = reverse("user-access-update", args=(self.attendant.pk,))
        self.client.force_login(self.root)
        response = self.client.post(
            update_url,
            {
                "username": self.attendant.username,
                "role": ROLE_ATTENDANCE,
                "capability_state__view_closings": "allow",
                "capability_state__create_orders": "deny",
            },
        )
        self.assertRedirects(response, reverse("user-access-list"))
        effects = dict(self.attendant.capability_overrides.values_list("capability", "effect"))
        self.assertEqual(effects[Capability.VIEW_CLOSINGS], "allow")
        self.assertEqual(effects[Capability.CREATE_ORDERS], "deny")
        self.assertTrue(AuditEvent.objects.filter(action="user.updated").exists())

        response = self.client.post(
            update_url,
            {
                "username": self.attendant.username,
                "role": ROLE_ATTENDANCE,
                "restore_profile_defaults": "1",
            },
        )
        self.assertRedirects(response, reverse("user-access-list"))
        self.assertFalse(self.attendant.capability_overrides.exists())

    def test_attendance_closing_direct_urls_follow_individual_grant(self):
        urls = (
            reverse("closing-list"),
            reverse("closing-detail", args=(self.closing.pk,)),
            reverse("closing-export-csv", args=(self.closing.pk,)),
        )
        self.client.force_login(self.attendant)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)

        for capability in (Capability.VIEW_CLOSINGS, Capability.EXPORT_CLOSINGS):
            UserCapabilityOverride.objects.create(
                user=self.attendant, capability=capability, effect="allow"
            )
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200)

        self.attendant.capability_overrides.filter(capability=Capability.VIEW_CLOSINGS).delete()
        self.attendant.__dict__.pop("_capability_override_cache", None)
        self.assertEqual(self.client.get(reverse("closing-list")).status_code, 403)

    def test_finance_keeps_closing_access_and_no_admin_escalation(self):
        self.assertTrue(user_has_capability(self.finance, Capability.VIEW_CLOSINGS))
        self.assertFalse(self.finance.is_staff)
        self.assertFalse(self.finance.is_superuser)
