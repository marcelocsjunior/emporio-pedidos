from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from customer_portal.models import CustomerPortalAccess
from orders.models import Company

from accounts.models import UserCapabilityOverride
from accounts.roles import ROLE_ADMIN, ROLE_OFFICIAL_SUPPORT
from accounts.user_management import UNASSIGNED_ROLE_LABEL, can_manage_user, display_role

User = get_user_model()


class InternalUserProfileManagementTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser(
            username="ti",
            email="ti@example.invalid",
            password="SenhaRoot123!",
        )
        self.client.force_login(self.root)
        Group.objects.get_or_create(name=ROLE_ADMIN)
        Group.objects.get_or_create(name=ROLE_OFFICIAL_SUPPORT)

    def create_internal_user(self, username="suporte", *, role=None):
        user = User.objects.create_user(
            username=username,
            display_name=username.title(),
            password="SenhaInicial123!",
            is_active=True,
        )
        if role:
            user.groups.add(Group.objects.get(name=role))
        return user

    def create_customer_user(self, username="cliente-portal"):
        user = User.objects.create_user(
            username=username,
            password="SenhaCliente123!",
            is_active=True,
        )
        company = Company.objects.create(name="Cliente Portal")
        CustomerPortalAccess.objects.create(user=user, company=company, active=True)
        return user

    def user_payload(self, user, *, role):
        return {
            "username": user.username,
            "display_name": user.display_name,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": role,
        }

    def test_root_list_shows_every_internal_account_and_excludes_customer_accounts(self):
        support = self.create_internal_user()
        customer = self.create_customer_user()

        response = self.client.get(reverse("user-access-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, support.username)
        self.assertContains(response, UNASSIGNED_ROLE_LABEL)
        self.assertNotContains(response, customer.username)

    def test_root_can_assign_profile_later_without_losing_individual_override(self):
        support = self.create_internal_user()
        UserCapabilityOverride.objects.create(
            user=support,
            capability="access_dashboard",
            effect="allow",
        )

        response = self.client.post(
            reverse("user-access-update", args=(support.pk,)),
            self.user_payload(support, role=ROLE_OFFICIAL_SUPPORT),
        )

        self.assertRedirects(response, reverse("user-access-list"))
        support.refresh_from_db()
        self.assertEqual(
            list(support.groups.values_list("name", flat=True)),
            [ROLE_OFFICIAL_SUPPORT],
        )
        self.assertTrue(
            support.capability_overrides.filter(
                capability="access_dashboard",
                effect="allow",
            ).exists()
        )

    def test_root_can_clear_profile_and_keep_account_visible(self):
        user = self.create_internal_user(username="operador", role=ROLE_ADMIN)

        response = self.client.post(
            reverse("user-access-update", args=(user.pk,)),
            self.user_payload(user, role=""),
        )

        self.assertRedirects(response, reverse("user-access-list"))
        user.refresh_from_db()
        self.assertFalse(user.groups.exists())
        self.assertEqual(display_role(user), UNASSIGNED_ROLE_LABEL)
        list_response = self.client.get(reverse("user-access-list"))
        self.assertContains(list_response, user.username)
        self.assertContains(list_response, UNASSIGNED_ROLE_LABEL)

    def test_root_can_create_internal_account_without_profile(self):
        response = self.client.post(
            reverse("user-access-create"),
            {
                "username": "perfil-pendente",
                "display_name": "Perfil Pendente",
                "first_name": "",
                "last_name": "",
                "initial_password": "SenhaTemporaria123!",
                "role": "",
            },
        )

        self.assertRedirects(response, reverse("user-access-list"))
        created = User.objects.get(username="perfil-pendente")
        self.assertTrue(created.is_active)
        self.assertTrue(created.must_change_password)
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertFalse(created.groups.exists())
        self.assertEqual(display_role(created), UNASSIGNED_ROLE_LABEL)

    def test_non_root_manager_cannot_create_account_without_profile(self):
        manager = self.create_internal_user(username="diretoria", role=ROLE_ADMIN)
        self.client.force_login(manager)

        response = self.client.post(
            reverse("user-access-create"),
            {
                "username": "sem-perfil-negado",
                "display_name": "Sem Perfil Negado",
                "first_name": "",
                "last_name": "",
                "initial_password": "SenhaTemporaria123!",
                "role": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selecione um perfil para esta conta.")
        self.assertFalse(User.objects.filter(username="sem-perfil-negado").exists())

    def test_customer_account_cannot_be_managed_from_internal_user_routes(self):
        customer = self.create_customer_user()

        self.assertFalse(can_manage_user(self.root, customer))
        edit_response = self.client.get(reverse("user-access-update", args=(customer.pk,)))
        toggle_response = self.client.post(
            reverse("user-access-toggle-active", args=(customer.pk,))
        )

        self.assertEqual(edit_response.status_code, 404)
        self.assertEqual(toggle_response.status_code, 404)
        customer.refresh_from_db()
        self.assertTrue(customer.is_active)

    def test_root_can_manage_unprofiled_internal_account(self):
        support = self.create_internal_user()

        self.assertTrue(can_manage_user(self.root, support))
