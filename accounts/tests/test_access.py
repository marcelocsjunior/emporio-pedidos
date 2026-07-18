from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from accounts.roles import ROLE_NAMES, ensure_roles


class RolesAndAuthenticationTests(TestCase):
    def test_role_bootstrap_is_idempotent(self):
        first = ensure_roles()
        first_counts = {name: group.permissions.count() for name, group in first.items()}
        second = ensure_roles()

        self.assertEqual(set(Group.objects.values_list("name", flat=True)), set(ROLE_NAMES))
        self.assertEqual(
            first_counts,
            {name: group.permissions.count() for name, group in second.items()},
        )
        self.assertTrue(all(count > 0 for count in first_counts.values()))

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_mandatory_password_change_blocks_operation_and_clears_flag(self):
        user = User.objects.create_user(
            username="operador",
            password="SenhaInicial!123",
            must_change_password=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("password_change"))

        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "SenhaInicial!123",
                "new_password1": "NovaSenhaSegura!456",
                "new_password2": "NovaSenhaSegura!456",
            },
        )
        self.assertRedirects(response, reverse("password_change_done"))
        user.refresh_from_db()
        self.assertFalse(user.must_change_password)
