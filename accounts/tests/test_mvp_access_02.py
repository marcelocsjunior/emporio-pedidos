from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.access import ROLE_CAPABILITIES, Capability, user_has_capability
from accounts.models import UserCapabilityOverride
from accounts.roles import ROLE_ATTENDANCE, ROLE_FINANCE, ROLE_SYSTEM_ADMIN, ensure_roles
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
        for user in (self.attendant, self.finance, self.system_admin):
            user.__dict__.pop("_capability_override_cache", None)

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

    def test_only_root_sees_and_changes_override_checklist(self):
        update_url = reverse("user-access-update", args=(self.attendant.pk,))
        self.client.force_login(self.system_admin)
        self.assertNotContains(self.client.get(update_url), "Funções permitidas")
        response = self.client.post(
            update_url,
            {
                "username": self.attendant.username,
                "role": ROLE_ATTENDANCE,
                "capabilities": [Capability.VIEW_CLOSINGS.value],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.attendant.capability_overrides.exists())

        self.client.force_login(self.root)
        self.assertContains(self.client.get(update_url), "Funções permitidas")

    def test_root_atomically_replaces_deltas_and_restores_profile(self):
        update_url = reverse("user-access-update", args=(self.attendant.pk,))
        selected = [
            capability.value
            for capability in ROLE_CAPABILITIES[ROLE_ATTENDANCE]
            if capability != Capability.CREATE_ORDERS
        ] + [Capability.VIEW_CLOSINGS.value]
        self.client.force_login(self.root)
        response = self.client.post(
            update_url,
            {
                "username": self.attendant.username,
                "role": ROLE_ATTENDANCE,
                "capabilities": selected,
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
