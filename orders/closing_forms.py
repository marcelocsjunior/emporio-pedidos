from __future__ import annotations

from datetime import date

from django import forms
from django.utils import timezone

from .models import Company, MonthlyClosing


class ClosingCompanyChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, company: Company) -> str:
        suffix = "" if company.active else " — inativa"
        return f"{company.name}{suffix}"


class ClosingGenerateForm(forms.Form):
    company = ClosingCompanyChoiceField(
        label="Empresa",
        queryset=Company.objects.none(),
    )
    reference_month = forms.DateField(
        label="Mês de referência",
        input_formats=("%Y-%m",),
        widget=forms.DateInput(format="%Y-%m", attrs={"type": "month"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.order_by("name")
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean_reference_month(self) -> date:
        reference_month = self.cleaned_data["reference_month"].replace(day=1)
        current_month = timezone.localdate().replace(day=1)
        if reference_month > current_month:
            raise forms.ValidationError("O fechamento não pode ser gerado para um mês futuro.")
        return reference_month


class ClosingNotesForm(forms.ModelForm):
    class Meta:
        model = MonthlyClosing
        fields = ("notes",)
        widgets = {"notes": forms.Textarea(attrs={"rows": 4, "class": "form-control"})}
