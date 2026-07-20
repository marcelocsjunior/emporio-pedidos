from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from accounts.access import Capability, user_has_capability
from accounts.roles import (
    ROLE_ADMIN,
    ROLE_ATTENDANCE,
    ROLE_EXPEDITION,
    ROLE_FINANCE,
    ROLE_NAMES,
    ROLE_PRODUCTION,
    ROLE_SUPPORT,
    ensure_roles,
)
from customer_portal.models import CustomerPortalAccess
from orders.models import AuditEvent


User = get_user_model()


class InternalAccessMVPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles = ensure_roles()
        cls.director = User.objects.create_user(
            username="director-test", password="safe-test-1"
        )
        cls.director.groups.add(roles[ROLE_ADMIN])
        cls.attendant = User.objects.create_user(
            username="attendant-test", password="safe-test-1"
        )
        cls.attendant.groups.add(roles[ROLE_ATTENDANCE])
        cls.support = User.objects.create_user(
            username="support-test", password="safe-test-1"
        )
        cls.support.groups.add(roles[ROLE_SUPPORT])
        cls.production = User.objects.create_user(
            username="production-test", password="safe-test-1"
        )
        cls.production.groups.add(roles[ROLE_PRODUCTION])
        cls.expedition = User.objects.create_user(
            username="expedition-test", password="safe-test-1"
        )
        cls.expedition.groups.add(roles[ROLE_EXPEDITION])
        cls.finance = User.objects.create_user(
            username="finance-test", password="safe-test-1"
        )
        cls.finance.groups.add(roles[ROLE_FINANCE])
        cls.legacy_reviewer = User.objects.create_user(
            username="legacy-reviewer-test", password="safe-test-1"
        )
        cls.legacy_reviewer.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="customer_portal",
                codename="review_customerorderrequest",
            )
        )

    def test_bootstrap_is_idempotent_and_preserves_legacy_groups(self):
        existing_users = set(User.objects.values_list("pk", flat=True))
        first = ensure_roles()
        second = ensure_roles()
        self.assertEqual(set(first), set(ROLE_NAMES))
        self.assertEqual(set(second), set(ROLE_NAMES))
        self.assertEqual(set(User.objects.values_list("pk", flat=True)), existing_users)
        self.assertTrue(Group.objects.filter(name=ROLE_SUPPORT).exists())

    def test_bootstrap_removes_selected_physical_delete_permissions(self):
        administrator = Group.objects.get(name=ROLE_ADMIN)
        removed_permissions = {
            ("accounts", "delete_user"),
            ("orders", "delete_order"),
            ("orders", "delete_company"),
            ("orders", "delete_product"),
            ("orders", "delete_monthlyclosing"),
        }
        permissions = Permission.objects.filter(
            content_type__app_label__in={"accounts", "orders"},
            codename__in={codename for _, codename in removed_permissions},
        )
        self.assertEqual(
            {
                (permission.content_type.app_label, permission.codename)
                for permission in permissions
            },
            removed_permissions,
        )

        administrator.permissions.add(*permissions)
        self.assertEqual(administrator.permissions.filter(pk__in=permissions).count(), 5)

        ensure_roles()
        administrator.refresh_from_db()
        self.assertFalse(administrator.permissions.filter(pk__in=permissions).exists())
        self.assertFalse(self.director.has_perm("accounts.delete_user"))
        self.assertFalse(self.director.has_perm("orders.delete_order"))
        self.assertFalse(self.director.has_perm("orders.delete_company"))
        self.assertFalse(self.director.has_perm("orders.delete_product"))
        self.assertFalse(self.director.has_perm("orders.delete_monthlyclosing"))

    def test_capability_matrix(self):
        self.assertTrue(user_has_capability(self.director, Capability.MANAGE_ATTENDANTS))
        self.assertTrue(user_has_capability(self.director, Capability.VIEW_AUDIT))
        self.assertTrue(user_has_capability(self.attendant, Capability.CREATE_ORDERS))
        self.assertFalse(user_has_capability(self.attendant, Capability.MANAGE_ATTENDANTS))
        self.assertTrue(user_has_capability(self.support, Capability.ACCESS_TECHNICAL_AREA))
        self.assertFalse(user_has_capability(self.support, Capability.VIEW_ORDERS))
        self.assertTrue(user_has_capability(self.production, Capability.VIEW_ORDERS))
        self.assertTrue(
            user_has_capability(self.production, Capability.CHANGE_ORDER_STATUS)
        )
        self.assertTrue(user_has_capability(self.expedition, Capability.VIEW_ORDERS))
        self.assertTrue(
            user_has_capability(self.expedition, Capability.CHANGE_ORDER_STATUS)
        )
        self.assertTrue(user_has_capability(self.finance, Capability.VIEW_REPORTS))
        self.assertTrue(user_has_capability(self.finance, Capability.VIEW_AUDIT))
        self.assertTrue(
            user_has_capability(self.legacy_reviewer, Capability.VIEW_ORDERS)
        )
        self.assertFalse(
            user_has_capability(self.legacy_reviewer, Capability.EDIT_ORDERS)
        )

    def test_director_creates_only_safe_attendant(self):
        self.client.force_login(self.director)
        response = self.client.post(
            reverse("attendant-create"),
            {
                "username": "new-attendant",
                "display_name": "Nova Atendente",
                "first_name": "Nova",
                "last_name": "Atendente",
                "initial_password": "safe-test-2",
                "is_staff": "1",
                "is_superuser": "1",
                "groups": str(Group.objects.get(name=ROLE_SUPPORT).pk),
            },
        )
        self.assertRedirects(response, reverse("attendant-list"))
        created = User.objects.get(username="new-attendant")
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertTrue(created.must_change_password)
        self.assertEqual(list(created.groups.values_list("name", flat=True)), [ROLE_ATTENDANCE])
        self.assertFalse(CustomerPortalAccess.objects.filter(user=created).exists())
        self.assertTrue(AuditEvent.objects.filter(action="attendant.created").exists())

    def test_director_suspends_and_reactivates_attendant(self):
        self.client.force_login(self.director)
        url = reverse("attendant-toggle-active", args=(self.attendant.pk,))
        self.client.post(url)
        self.attendant.refresh_from_db()
        self.assertFalse(self.attendant.is_active)
        self.client.post(url)
        self.attendant.refresh_from_db()
        self.assertTrue(self.attendant.is_active)
        self.assertTrue(AuditEvent.objects.filter(action="attendant.suspended").exists())
        self.assertTrue(AuditEvent.objects.filter(action="attendant.reactivated").exists())

    def test_non_directors_cannot_manage_attendants_by_direct_url(self):
        for user in (self.attendant, self.support):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("attendant-list")).status_code, 403)
            self.assertEqual(self.client.post(reverse("attendant-create"), {}).status_code, 403)

    def test_support_only_reaches_sanitized_technical_area(self):
        self.client.force_login(self.support)
        response = self.client.get(reverse("technical-area"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Autenticação funcional")
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("order-list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("company-list")).status_code, 403)

    def test_attendant_cannot_access_audit_or_technical_area(self):
        self.client.force_login(self.attendant)
        self.assertEqual(self.client.get(reverse("audit-list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("technical-area")).status_code, 403)
