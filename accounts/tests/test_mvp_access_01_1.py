from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse

from accounts.access import Capability, is_root_system_admin, user_has_capability
from accounts.roles import (
    ROLE_ADMIN,
    ROLE_ATTENDANCE,
    ROLE_EXPEDITION,
    ROLE_FINANCE,
    ROLE_PRODUCTION,
    ROLE_SUPPORT,
    ROLE_SYSTEM_ADMIN,
    ensure_roles,
)
from orders.models import AuditEvent

User = get_user_model()


class RootAndSystemAdministrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles = ensure_roles()
        cls.root = User.objects.create_user(
            username="ti",
            password="safe-root-password",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        cls.system_admin = User.objects.create_user(
            username="system-admin",
            password="safe-system-password",
            is_staff=False,
            is_superuser=False,
        )
        cls.system_admin.groups.add(roles[ROLE_SYSTEM_ADMIN])
        cls.other_system_admin = User.objects.create_user(
            username="system-admin-2", password="safe-system-password"
        )
        cls.other_system_admin.groups.add(roles[ROLE_SYSTEM_ADMIN])
        cls.attendant = User.objects.create_user(
            username="managed-attendant", password="safe-attendant-password"
        )
        cls.attendant.groups.add(roles[ROLE_ATTENDANCE])

    def test_root_identity_is_exact_and_requires_superuser(self):
        similar = User.objects.create_user(
            username="Ti", password="safe-password", is_superuser=True
        )
        unpromoted = User.objects.create_user(username="ti-unpromoted", password="safe")
        unpromoted.username = "ti"
        self.assertTrue(is_root_system_admin(self.root))
        self.assertFalse(is_root_system_admin(similar))
        self.assertFalse(is_root_system_admin(unpromoted))

    def test_root_has_every_application_capability(self):
        self.assertTrue(
            all(user_has_capability(self.root, capability) for capability in Capability)
        )

    def test_system_admin_has_application_access_but_not_privileged_management(self):
        for capability in Capability:
            expected = capability != Capability.MANAGE_SYSTEM_ADMINS
            self.assertEqual(user_has_capability(self.system_admin, capability), expected)
        self.assertFalse(self.system_admin.is_staff)
        self.assertFalse(self.system_admin.is_superuser)
        expected_permissions = (
            "orders.view_order",
            "orders.add_order",
            "orders.change_order",
            "orders.view_company",
            "orders.view_monthlyclosing",
            "orders.view_auditevent",
            "customer_portal.review_customerorderrequest",
            "intelligence.process_ai_events",
        )
        self.assertTrue(all(self.system_admin.has_perm(perm) for perm in expected_permissions))
        self.assertFalse(self.system_admin.has_perm("accounts.delete_user"))

    def test_only_root_accesses_django_admin(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)
        self.client.force_login(self.system_admin)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    def test_root_creates_system_admin_with_safe_django_flags(self):
        self.client.force_login(self.root)
        response = self.client.post(
            reverse("user-access-create"),
            {
                "username": "new-system-admin",
                "display_name": "Nova Administração",
                "first_name": "Nova",
                "last_name": "Administração",
                "role": ROLE_SYSTEM_ADMIN,
                "initial_password": "safe-initial-password",
            },
        )
        self.assertRedirects(response, reverse("user-access-list"))
        created = User.objects.get(username="new-system-admin")
        self.assertEqual(list(created.groups.values_list("name", flat=True)), [ROLE_SYSTEM_ADMIN])
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertTrue(created.must_change_password)
        self.assertTrue(AuditEvent.objects.filter(action="system_admin.created").exists())

    def test_root_edits_suspends_and_reactivates_system_admin(self):
        self.client.force_login(self.root)
        update = self.client.post(
            reverse("user-access-update", args=(self.other_system_admin.pk,)),
            {
                "username": self.other_system_admin.username,
                "display_name": "Administração atualizada",
                "first_name": "Administração",
                "last_name": "Atualizada",
                "role": ROLE_SYSTEM_ADMIN,
            },
        )
        self.assertRedirects(update, reverse("user-access-list"))
        toggle_url = reverse(
            "user-access-toggle-active", args=(self.other_system_admin.pk,)
        )
        self.client.post(toggle_url)
        self.other_system_admin.refresh_from_db()
        self.assertFalse(self.other_system_admin.is_active)
        self.client.post(toggle_url)
        self.other_system_admin.refresh_from_db()
        self.assertTrue(self.other_system_admin.is_active)
        self.assertTrue(AuditEvent.objects.filter(action="system_admin.updated").exists())
        self.assertTrue(AuditEvent.objects.filter(action="user.suspended").exists())
        self.assertTrue(AuditEvent.objects.filter(action="user.reactivated").exists())

    def test_system_admin_creates_every_lower_profile(self):
        self.client.force_login(self.system_admin)
        lower_roles = (
            ROLE_ADMIN,
            ROLE_ATTENDANCE,
            ROLE_SUPPORT,
            ROLE_PRODUCTION,
            ROLE_EXPEDITION,
            ROLE_FINANCE,
        )
        for index, role in enumerate(lower_roles):
            response = self.client.post(
                reverse("user-access-create"),
                {
                    "username": f"lower-{index}",
                    "display_name": role,
                    "first_name": "Perfil",
                    "last_name": "Inferior",
                    "role": role,
                    "initial_password": "safe-initial-password",
                },
            )
            self.assertRedirects(response, reverse("user-access-list"))
            created = User.objects.get(username=f"lower-{index}")
            self.assertEqual(created.groups.get().name, role)
            self.assertFalse(created.is_staff)
            self.assertFalse(created.is_superuser)

    def test_system_admin_cannot_create_or_manage_system_admin(self):
        self.client.force_login(self.system_admin)
        create_response = self.client.post(
            reverse("user-access-create"),
            {
                "username": "forbidden-system-admin",
                "role": ROLE_SYSTEM_ADMIN,
                "initial_password": "safe-initial-password",
            },
        )
        self.assertEqual(create_response.status_code, 200)
        self.assertFalse(User.objects.filter(username="forbidden-system-admin").exists())
        self.assertEqual(
            self.client.get(
                reverse("user-access-update", args=(self.other_system_admin.pk,))
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("user-access-toggle-active", args=(self.other_system_admin.pk,))
            ).status_code,
            403,
        )
        self.other_system_admin.refresh_from_db()
        self.assertTrue(self.other_system_admin.is_active)

    def test_manipulated_post_never_elevates_privileges(self):
        self.client.force_login(self.system_admin)
        response = self.client.post(
            reverse("user-access-create"),
            {
                "username": "manipulated-user",
                "role": ROLE_ATTENDANCE,
                "initial_password": "safe-initial-password",
                "is_staff": "1",
                "is_superuser": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="manipulated-user").exists())
        self.assertTrue(
            AuditEvent.objects.filter(action="user.privilege_escalation_denied").exists()
        )

    def test_root_changes_own_password(self):
        self.client.force_login(self.root)
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "safe-root-password",
                "new_password1": "new-safe-root-password",
                "new_password2": "new-safe-root-password",
            },
        )
        self.assertRedirects(response, reverse("password_change_done"))
        self.root.refresh_from_db()
        self.assertTrue(self.root.check_password("new-safe-root-password"))

    def test_root_updates_basic_data_but_protected_fields_remain(self):
        self.client.force_login(self.root)
        response = self.client.post(
            reverse("user-access-update", args=(self.root.pk,)),
            {
                "username": "ti",
                "display_name": "Equipe Técnica",
                "first_name": "Equipe",
                "last_name": "Técnica",
                "role": "root",
            },
        )
        self.assertRedirects(response, reverse("user-access-list"))
        self.root.refresh_from_db()
        self.assertEqual(self.root.username, "ti")
        self.assertEqual(self.root.display_name, "Equipe Técnica")
        self.assertTrue(self.root.is_active)
        self.assertTrue(self.root.is_staff)
        self.assertTrue(self.root.is_superuser)

    def test_root_cannot_be_renamed_suspended_or_deleted_through_user_area(self):
        self.client.force_login(self.root)
        rename = self.client.post(
            reverse("user-access-update", args=(self.root.pk,)),
            {"username": "other", "display_name": "", "role": "root"},
        )
        self.assertEqual(rename.status_code, 200)
        self.assertEqual(
            self.client.post(
                reverse("user-access-toggle-active", args=(self.root.pk,))
            ).status_code,
            403,
        )
        delete_url = reverse("admin:accounts_user_delete", args=(self.root.pk,))
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        self.root.refresh_from_db()
        self.assertEqual(self.root.username, "ti")
        self.assertTrue(self.root.is_active)
        self.assertTrue(User.objects.filter(pk=self.root.pk).exists())

    def test_django_admin_never_grants_staff_or_superuser_to_another_account(self):
        self.client.force_login(self.root)
        target = self.attendant
        response = self.client.post(
            reverse("admin:accounts_user_change", args=(target.pk,)),
            {
                "username": target.username,
                "password": target.password,
                "first_name": target.first_name,
                "last_name": target.last_name,
                "email": target.email,
                "is_active": "on",
                "is_staff": "on",
                "is_superuser": "on",
                "date_joined_0": target.date_joined.date().isoformat(),
                "date_joined_1": target.date_joined.time().strftime("%H:%M:%S"),
                "display_name": target.display_name,
            },
        )
        self.assertIn(response.status_code, (200, 302))
        target.refresh_from_db()
        self.assertFalse(target.is_staff)
        self.assertFalse(target.is_superuser)

    def test_director_still_manages_only_attendants(self):
        director = User.objects.create_user(username="director", password="safe-password")
        director.groups.add(ensure_roles()[ROLE_ADMIN])
        self.client.force_login(director)
        response = self.client.get(reverse("user-access-list"))
        self.assertContains(response, self.attendant.username)
        self.assertNotContains(response, self.system_admin.username)
        self.assertEqual(
            self.client.get(
                reverse("user-access-update", args=(self.system_admin.pk,))
            ).status_code,
            403,
        )


class BootstrapRootAdminCommandTests(TestCase):
    def test_rejects_wrong_username_and_missing_root(self):
        with self.assertRaises(CommandError):
            call_command("bootstrap_root_admin", username="other")
        with self.assertRaises(CommandError):
            call_command("bootstrap_root_admin", username="ti")
        self.assertEqual(User.objects.count(), 0)

    def test_dry_run_does_not_change_user(self):
        user = User.objects.create_user(username="ti", password="original-password")
        password_hash = user.password
        output = StringIO()
        call_command("bootstrap_root_admin", username="ti", dry_run=True, stdout=output)
        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.password, password_hash)
        self.assertIn("Dry-run", output.getvalue())

    def test_promotes_existing_root_idempotently_without_changing_password(self):
        user = User.objects.create_user(
            username="ti", password="original-password", is_active=False
        )
        password_hash = user.password
        first_output = StringIO()
        call_command("bootstrap_root_admin", username="ti", stdout=first_output)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.password, password_hash)
        self.assertEqual(AuditEvent.objects.filter(action="root_admin.promoted").count(), 1)
        call_command("bootstrap_root_admin", username="ti", stdout=StringIO())
        self.assertEqual(AuditEvent.objects.filter(action="root_admin.promoted").count(), 1)
        self.assertNotIn("password", first_output.getvalue().lower())
