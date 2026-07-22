from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from .access import (
    CAPABILITY_CATALOG,
    CONFIGURABLE_CAPABILITIES,
    ROLE_CAPABILITIES,
    ROOT_USERNAME,
    Capability,
    effective_capabilities_for_user,
    is_root_system_admin,
)
from .user_management import roles_actor_can_assign, user_role

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
    role = forms.ChoiceField(label="Perfil")
    initial_password = forms.CharField(
        label="Senha inicial",
        strip=False,
        min_length=8,
        widget=forms.PasswordInput,
        required=False,
        help_text="Obrigatória na criação; a troca será exigida no primeiro acesso.",
    )
    capabilities = forms.MultipleChoiceField(
        label="Funções permitidas",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    restore_profile_defaults = forms.BooleanField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = User
        fields = ("username", "display_name", "first_name", "last_name")

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        allowed = roles_actor_can_assign(actor)
        self.fields["role"].choices = ((role, role) for role in allowed)
        if self.instance.pk:
            current_role = user_role(self.instance)
            self.fields["role"].initial = current_role
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
        can_customize = is_root_system_admin(actor) and not (
            self.instance.pk and self.instance.username == ROOT_USERNAME
        )
        if can_customize:
            self.fields["capabilities"].choices = (
                (item.capability.value, item.name)
                for item in CAPABILITY_CATALOG
                if item.configurable
            )
            if self.instance.pk:
                self.fields["capabilities"].initial = tuple(
                    capability.value
                    for capability in effective_capabilities_for_user(self.instance)
                )
            else:
                default_role = allowed[0] if allowed else None
                self.fields["capabilities"].initial = tuple(
                    capability.value for capability in ROLE_CAPABILITIES.get(default_role, ())
                )
        else:
            self.fields.pop("capabilities")
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
            self.instance.pk and role == user_role(self.instance)
        )
        if (
            not editing_own_root
            and not preserving_legacy_role
            and role not in roles_actor_can_assign(self.actor)
        ):
            raise ValidationError("Perfil fora do escopo autorizado.")
        if self.instance.pk and self.instance.username == ROOT_USERNAME:
            if self.data.get("username", ROOT_USERNAME) != ROOT_USERNAME:
                raise ValidationError("O login da conta raiz é imutável.")
        submitted_capabilities = set(self.data.getlist("capabilities"))
        catalog_values = {capability.value for capability in CONFIGURABLE_CAPABILITIES}
        if submitted_capabilities and not is_root_system_admin(self.actor):
            raise ValidationError("Somente o Administrador Raiz pode personalizar funções.")
        if submitted_capabilities - catalog_values:
            raise ValidationError("Capability inválida ou protegida pelo sistema.")
        if (
            self.instance.pk
            and self.instance.username == ROOT_USERNAME
            and "capabilities" in self.data
        ):
            raise ValidationError("A conta raiz não aceita personalizações.")
        return cleaned

    def capability_deltas(self) -> tuple[set[Capability], set[Capability]]:
        if "capabilities" not in self.fields:
            return set(), set()
        role = self.cleaned_data["role"]
        base = set(ROLE_CAPABILITIES.get(role, ()))
        selected = (
            {Capability(value) for value in self.cleaned_data["capabilities"]}
            if "capabilities" in self.data
            else base
        )
        if self.cleaned_data.get("restore_profile_defaults"):
            selected = base
        return selected - base, base - selected

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
                user.groups.set((Group.objects.get(name=self.cleaned_data["role"]),))
        return user
