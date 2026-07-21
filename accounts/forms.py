from django import forms
from django.contrib.auth import get_user_model

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
