from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from .access import (
    CAPABILITY_CATALOG,
    CONFIGURABLE_CAPABILITIES,
    ROOT_USERNAME,
    Capability,
    effective_capabilities_for_user,
    is_root_system_admin,
    user_has_capability,
)
from .user_management import UNASSIGNED_ROLE_LABEL, roles_actor_can_assign, user_role

User = get_user_model()


class StyledFormMixin:
    def _style_fields(self):
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class AttendantCreateForm(StyledFormMixin, forms.ModelForm):
    initial_password = forms.CharField(
        label="Senha inicial",
        strip=False,
        min_length=8,
        widget=forms.PasswordInput,
        help_text="A pessoa deverá trocar esta senha no primeiro acesso.",
    )

    class Meta:
        model = User
        fields = ("username", "display_name", "first_name", "last_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["initial_password"])
        user.must_change_password = True
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user


class AttendantUpdateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("username", "display_name", "first_name", "last_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class ManagedUserForm(StyledFormMixin, forms.ModelForm):
    CAPABILITY_FIELD_PREFIX = "capability_state__"
    CAPABILITY_STATE_CHOICES = (
        ("default", "Padrão do perfil"),
        ("allow", "Permitido"),
        ("deny", "Bloqueado"),
    )
    role = forms.ChoiceField(label="Perfil", required=False)
    initial_password = forms.CharField(
        label="Senha inicial",
        strip=False,
        min_length=8,
        widget=forms.PasswordInput,
        required=False,
        help_text="Obrigatória na criação; a troca será exigida no primeiro acesso.",
    )
    restore_profile_defaults = forms.BooleanField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = User
        fields = ("username", "display_name", "first_name", "last_name")

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        allowed = tuple(roles_actor_can_assign(actor))
        self.can_defer_role = is_root_system_admin(actor)
        role_choices = [(role, role) for role in allowed]
        if self.can_defer_role:
            role_choices.insert(0, ("", UNASSIGNED_ROLE_LABEL))
            self.fields["role"].help_text = (
                "Opcional para a conta raiz. O perfil pode ser atribuído ou alterado depois."
            )
        self.fields["role"].choices = role_choices
        if self.instance.pk:
            current_role = user_role(self.instance)
            self.fields["role"].initial = current_role or ""
            if current_role and current_role not in allowed:
                self.fields["role"].choices = (
                    *self.fields["role"].choices,
                    (current_role, current_role),
                )
            if self.instance.username == ROOT_USERNAME:
                self.fields["username"].disabled = True
                self.fields["role"].disabled = True
                self.fields["role"].choices = (("root", "Administrador Raiz do Sistema"),)
                self.fields["role"].initial = "root"
        else:
            self.fields["initial_password"].required = True
        can_customize = user_has_capability(actor, Capability.MANAGE_ATTENDANTS) and not (
            self.instance.pk and self.instance.username == ROOT_USERNAME
        )
        self.customizable_capabilities = frozenset()
        if can_customize:
            actor_capabilities = effective_capabilities_for_user(actor)
            self.customizable_capabilities = frozenset(
                capability
                for capability in CONFIGURABLE_CAPABILITIES
                if is_root_system_admin(actor) or capability in actor_capabilities
            )
            existing = (
                dict(self.instance.capability_overrides.values_list("capability", "effect"))
                if self.instance.pk
                else {}
            )
            for item in CAPABILITY_CATALOG:
                if item.capability not in self.customizable_capabilities:
                    continue
                self.fields[self.capability_field_name(item.capability)] = forms.ChoiceField(
                    label=item.name,
                    choices=self.CAPABILITY_STATE_CHOICES,
                    initial=existing.get(item.capability.value, "default"),
                    required=False,
                    widget=forms.RadioSelect,
                )
        else:
            self.fields.pop("restore_profile_defaults")
        self._style_fields()

    def clean(self):
        cleaned = super().clean()
        forbidden = {"is_staff", "is_superuser", "user_permissions", "groups"}
        if forbidden.intersection(self.data):
            raise ValidationError("Tentativa de alterar privilégios protegidos.")
        role = cleaned.get("role")
        editing_own_root = (
            self.instance.pk
            and self.instance.username == ROOT_USERNAME
            and self.instance.pk == self.actor.pk
            and is_root_system_admin(self.actor)
        )
        preserving_legacy_role = bool(
            self.instance.pk and role and role == user_role(self.instance)
        )
        if not editing_own_root:
            if not role:
                if not self.can_defer_role:
                    raise ValidationError("Selecione um perfil para esta conta.")
            elif not preserving_legacy_role and role not in roles_actor_can_assign(self.actor):
                raise ValidationError("Perfil fora do escopo autorizado.")
        if self.instance.pk and self.instance.username == ROOT_USERNAME:
            if self.data.get("username", ROOT_USERNAME) != ROOT_USERNAME:
                raise ValidationError("O login da conta raiz é imutável.")
        submitted_fields = {
            key for key in self.data if key.startswith(self.CAPABILITY_FIELD_PREFIX)
        }
        if "capabilities" in self.data:
            raise ValidationError("Formato antigo de capabilities não é aceito.")
        allowed_fields = {
            self.capability_field_name(capability)
            for capability in self.customizable_capabilities
        }
        if submitted_fields - allowed_fields:
            raise ValidationError("Capability inválida, protegida ou fora do escopo do gestor.")
        if (
            self.instance.pk
            and self.instance.username == ROOT_USERNAME
            and submitted_fields
        ):
            raise ValidationError("A conta raiz não aceita personalizações.")
        return cleaned

    def capability_deltas(self) -> tuple[set[Capability], set[Capability]]:
        if not self.customizable_capabilities:
            return set(), set()
        if self.cleaned_data.get("restore_profile_defaults"):
            return set(), set()
        allowed = {
            capability
            for capability in self.customizable_capabilities
            if self.cleaned_data.get(self.capability_field_name(capability)) == "allow"
        }
        denied = {
            capability
            for capability in self.customizable_capabilities
            if self.cleaned_data.get(self.capability_field_name(capability)) == "deny"
        }
        return allowed, denied

    def capability_controls_submitted(self) -> bool:
        return bool(
            self.cleaned_data.get("restore_profile_defaults")
            or any(
                self.capability_field_name(capability) in self.data
                for capability in self.customizable_capabilities
            )
        )

    @classmethod
    def capability_field_name(cls, capability: Capability) -> str:
        return f"{cls.CAPABILITY_FIELD_PREFIX}{capability.value}"

    def save(self, commit=True):
        user = super().save(commit=False)
        editing_root = bool(user.pk and user.username == ROOT_USERNAME)
        if not editing_root:
            user.is_staff = False
            user.is_superuser = False
        if not user.pk:
            user.is_active = True
            user.must_change_password = True
            user.set_password(self.cleaned_data["initial_password"])
        if commit:
            user.save()
            if not editing_root:
                role = self.cleaned_data.get("role")
                if role:
                    user.groups.set((Group.objects.get(name=role),))
                else:
                    user.groups.clear()
        return user
