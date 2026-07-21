from __future__ import annotations

import re

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError

from accounts.access import effective_capabilities_for_user
from orders.models import Company
from orders.validators import digits_only, validate_cnpj, validate_cpf, validate_numeric_text

from .models import CustomerPortalAccess

User = get_user_model()
PROTECTED_USERNAMES = {"ti", "bio", "rafa"}


def normalize_phone(value: str) -> str:
    return digits_only(value)


def eligible_portal_users():
    return (
        User.objects.filter(
            is_staff=False,
            is_superuser=False,
            groups__isnull=True,
            customer_portal_access__isnull=True,
        )
        .exclude(username__in=PROTECTED_USERNAMES)
        .distinct()
        .order_by("username")
    )


def validate_eligible_user(user):
    if user.username.lower() in PROTECTED_USERNAMES:
        raise ValidationError("Este usuário é protegido e não pode ser vinculado ao portal.")
    if user.is_staff or user.is_superuser:
        raise ValidationError("Usuários administrativos não podem ser vinculados ao portal.")
    if (
        user.groups.exists()
        or user.user_permissions.exists()
        or effective_capabilities_for_user(user)
    ):
        raise ValidationError("O usuário possui acesso interno e não pode ser vinculado ao portal.")
    if CustomerPortalAccess.objects.filter(user=user).exists():
        raise ValidationError("O usuário já possui um acesso de cliente.")
    return user


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-control"


class PublicAccessRequestForm(StyledForm):
    customer_name = forms.CharField(label="Empresa ou cliente", max_length=180)
    entity_type = forms.ChoiceField(
        label="Pessoa física ou jurídica", choices=Company.EntityType.choices
    )
    document = forms.CharField(label="CPF/CNPJ", max_length=18)
    requester_name = forms.CharField(label="Seu nome", max_length=150)
    email = forms.EmailField(label="E-mail", max_length=254)
    phone = forms.CharField(label="Telefone", max_length=30)
    message = forms.CharField(
        label="Mensagem", max_length=1000, required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_customer_name(self):
        return self.cleaned_data["customer_name"].strip()

    def clean_requester_name(self):
        return self.cleaned_data["requester_name"].strip()

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_phone(self):
        raw = self.cleaned_data["phone"]
        if re.search(r"[A-Za-z]", raw):
            raise ValidationError("Informe um telefone válido.")
        phone = normalize_phone(raw)
        if not 8 <= len(phone) <= 15:
            raise ValidationError("Informe um telefone válido.")
        return phone

    def clean_document(self):
        raw = self.cleaned_data["document"]
        validate_numeric_text(raw, label="CPF/CNPJ")
        document = digits_only(raw)
        entity_type = self.cleaned_data.get("entity_type")
        if entity_type == Company.EntityType.INDIVIDUAL:
            validate_cpf(document)
        elif entity_type == Company.EntityType.COMPANY:
            validate_cnpj(document)
        return document


class PortalUserCreateForm(StyledForm, forms.ModelForm):
    company = forms.ModelChoiceField(queryset=Company.objects.filter(active=True))
    password1 = forms.CharField(label="Senha inicial", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar senha", strip=False, widget=forms.PasswordInput)
    active = forms.BooleanField(label="Acesso ativo", required=False, initial=True)

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if username.lower() in PROTECTED_USERNAMES:
            raise ValidationError("Este identificador é reservado.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Já existe um usuário com este e-mail. Use o vínculo existente.")
        return email

    def clean(self):
        cleaned = super().clean()
        forbidden = {"is_staff", "is_superuser", "groups", "user_permissions"}
        if forbidden.intersection(self.data):
            raise ValidationError("Tentativa de alterar privilégios protegidos.")
        if cleaned.get("password1") != cleaned.get("password2"):
            self.add_error("password2", "As senhas não coincidem.")
        password = cleaned.get("password1")
        if password:
            candidate = User(username=cleaned.get("username", ""), email=cleaned.get("email", ""))
            password_validation.validate_password(password, candidate)
        return cleaned


class PortalUserLinkForm(StyledForm):
    company = forms.ModelChoiceField(queryset=Company.objects.filter(active=True))
    user = forms.ModelChoiceField(queryset=User.objects.none(), label="Usuário do portal")
    active = forms.BooleanField(label="Acesso ativo", required=False, initial=True)
    confirm = forms.BooleanField(label="Confirmo a empresa selecionada")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = eligible_portal_users()

    def clean_user(self):
        return validate_eligible_user(self.cleaned_data["user"])


class AccessStatusForm(StyledForm):
    reason = forms.CharField(
        label="Motivo", max_length=300, required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    confirm = forms.BooleanField(label="Confirmo esta alteração")


class AdminPasswordResetForm(StyledForm):
    password1 = forms.CharField(label="Nova senha", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(
        label="Confirmar nova senha", strip=False, widget=forms.PasswordInput
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password1") != cleaned.get("password2"):
            self.add_error("password2", "As senhas não coincidem.")
        if cleaned.get("password1"):
            password_validation.validate_password(cleaned["password1"], self.user)
        return cleaned


class AccessRequestReviewForm(StyledForm):
    company = forms.ModelChoiceField(
        queryset=Company.objects.filter(active=True), required=False, label="Empresa vinculada"
    )
    user = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, label="Usuário do portal"
    )
    decision_notes = forms.CharField(
        label="Justificativa interna",
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    confirm = forms.BooleanField(label="Confirmo a decisão", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = (
            User.objects.filter(is_staff=False, is_superuser=False, groups__isnull=True)
            .exclude(username__in=PROTECTED_USERNAMES)
            .distinct()
            .order_by("username")
        )

    def clean_user(self):
        user = self.cleaned_data.get("user")
        if not user:
            return None
        if user.username.lower() in PROTECTED_USERNAMES or user.is_staff or user.is_superuser:
            raise ValidationError("Este usuário não pode ser vinculado ao portal.")
        if (
            user.groups.exists()
            or user.user_permissions.exists()
            or effective_capabilities_for_user(user)
        ):
            raise ValidationError("O usuário possui acesso interno.")
        return user
