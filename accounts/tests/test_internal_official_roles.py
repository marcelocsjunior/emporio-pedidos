from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from accounts.access import Capability, effective_capabilities_for_user
from accounts.forms import ManagedUserForm
from accounts.models import UserCapabilityOverride
from accounts.roles import OFFICIAL_ROLE_NAMES, ROLE_ADMIN, ROLE_ATTENDANCE, ensure_roles

User = get_user_model()


class InternalOfficialRolesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles = ensure_roles()
        cls.actor = User.objects.create_user(username="bio", password="safe-password")
        cls.actor.groups.add(roles[ROLE_ADMIN])
        cls.existing = User.objects.create_user(
            username="existing-user", password="existing-password", must_change_password=False
        )
        cls.existing.groups.add(roles[ROLE_ATTENDANCE])

    def setUp(self):
        self.client.force_login(self.actor)

    def test_create_and_edit_render_exactly_the_seven_official_roles(self):
        create = self.client.get(reverse("user-access-create"))
        edit = self.client.get(reverse("user-access-update", args=(self.existing.pk,)))

        for response in (create, edit):
            self.assertEqual(response.status_code, 200)
            choices = tuple(
                value
                for value, _label in response.context["form"].fields["role"].choices
            )
            self.assertEqual(choices, OFFICIAL_ROLE_NAMES)
            for role in OFFICIAL_ROLE_NAMES:
                self.assertContains(response, f'value="{role}"')

    def test_every_official_role_can_be_selected_and_persists_without_escalation(self):
        for index, role in enumerate(OFFICIAL_ROLE_NAMES):
            response = self.client.post(
                reverse("user-access-create"),
                {
                    "username": f"official-role-{index}",
                    "display_name": role,
                    "role": role,
                    "initial_password": "safe-initial-password",
                },
            )
            self.assertRedirects(response, reverse("user-access-list"))
            created = User.objects.get(username=f"official-role-{index}")
            created.refresh_from_db()
            self.assertEqual(created.groups.get().name, role)
            self.assertFalse(created.is_staff)
            self.assertFalse(created.is_superuser)
            self.assertTrue(created.must_change_password)
            if role not in {ROLE_ADMIN, ROLE_ATTENDANCE}:
                self.assertFalse(created.get_all_permissions())
                self.assertFalse(effective_capabilities_for_user(created))

    def test_existing_user_and_bio_are_unchanged_when_form_is_only_displayed(self):
        existing_snapshot = (
            self.existing.password,
            self.existing.must_change_password,
            tuple(self.existing.groups.values_list("name", flat=True)),
        )
        bio_snapshot = (
            self.actor.password,
            self.actor.is_staff,
            self.actor.is_superuser,
            tuple(self.actor.groups.values_list("name", flat=True)),
        )

        self.client.get(reverse("user-access-create"))
        self.client.get(reverse("user-access-update", args=(self.existing.pk,)))
        self.existing.refresh_from_db()
        self.actor.refresh_from_db()

        self.assertEqual(
            (
                self.existing.password,
                self.existing.must_change_password,
                tuple(self.existing.groups.values_list("name", flat=True)),
            ),
            existing_snapshot,
        )
        self.assertEqual(
            (
                self.actor.password,
                self.actor.is_staff,
                self.actor.is_superuser,
                tuple(self.actor.groups.values_list("name", flat=True)),
            ),
            bio_snapshot,
        )

    def test_invalid_role_is_rejected(self):
        form = ManagedUserForm(
            {
                "username": "invalid-role-user",
                "role": "Support",
                "initial_password": "safe-initial-password",
            },
            actor=self.actor,
        )
        self.assertFalse(form.is_valid())
        self.assertFalse(User.objects.filter(username="invalid-role-user").exists())

    def test_delegated_attendant_manager_cannot_assign_administrator(self):
        delegated = User.objects.create_user(
            username="delegated-manager", password="safe-password"
        )
        delegated.groups.add(Group.objects.get(name=ROLE_ATTENDANCE))
        UserCapabilityOverride.objects.create(
            user=delegated,
            capability=Capability.MANAGE_ATTENDANTS.value,
            effect=UserCapabilityOverride.Effect.ALLOW,
        )
        form = ManagedUserForm(actor=delegated)
        self.assertEqual(tuple(form.fields["role"].choices), ((ROLE_ATTENDANCE, ROLE_ATTENDANCE),))

        manipulated = ManagedUserForm(
            {
                "username": "escalated-admin",
                "role": ROLE_ADMIN,
                "initial_password": "safe-initial-password",
            },
            actor=delegated,
        )
        self.assertFalse(manipulated.is_valid())
        self.assertFalse(User.objects.filter(username="escalated-admin").exists())

    def test_role_bootstrap_is_idempotent_and_has_no_duplicates(self):
        ensure_roles()
        ensure_roles()
        for role in OFFICIAL_ROLE_NAMES:
            self.assertEqual(Group.objects.filter(name=role).count(), 1)
