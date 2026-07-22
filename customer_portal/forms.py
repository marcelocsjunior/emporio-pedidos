from __future__ import annotations

from datetime import date
from decimal import Decimal

from django import forms
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone

from orders.models import Product

from .models import CustomerDeliveryLocation, CustomerOrderRequest, CustomerOrderRequestItem


class PortalModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class CustomerRequestForm(PortalModelForm):
    creation_key = forms.CharField(widget=forms.HiddenInput, min_length=32, max_length=64)

    class Meta:
        model = CustomerOrderRequest
        fields = ("delivery_date", "delivery_time", "delivery_location", "notes")
        widgets = {
            "delivery_date": forms.DateInput(attrs={"type": "date"}),
            "delivery_time": forms.TimeInput(attrs={"type": "time"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, company, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)
        location_filter = Q(company=company, active=True)
        if self.instance and self.instance.pk and self.instance.delivery_location_id:
            location_filter |= Q(pk=self.instance.delivery_location_id)
        self.fields["delivery_location"].queryset = CustomerDeliveryLocation.objects.filter(
            location_filter
        ).order_by("label")
        self.fields["delivery_location"].empty_label = "Selecione um local cadastrado"
        active_locations = list(
            CustomerDeliveryLocation.objects.filter(company=company, active=True).order_by("label")
        )
        self.no_active_delivery_locations = not active_locations
        if (
            not self.is_bound
            and len(active_locations) == 1
            and not getattr(self.instance, "delivery_location_id", None)
        ):
            self.initial["delivery_location"] = active_locations[0].pk

    def clean_delivery_date(self) -> date:
        value = self.cleaned_data["delivery_date"]
        if value < timezone.localdate():
            raise forms.ValidationError("A data de entrega não pode estar no passado.")
        return value

    def clean_delivery_location(self) -> CustomerDeliveryLocation:
        location = self.cleaned_data["delivery_location"]
        if location.company_id != self.company.pk:
            raise forms.ValidationError("Local de entrega inválido para esta empresa.")
        if not location.active and location.pk != self.instance.delivery_location_id:
            raise forms.ValidationError("O local de entrega está inativo.")
        return location


class PortalProductChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, product: Product) -> str:
        price = f"{product.unit_price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        category = f" · {product.category}" if product.category else ""
        return f"{product.name}{category} — R$ {price}"


class CustomerRequestItemForm(PortalModelForm):
    product = PortalProductChoiceField(queryset=Product.objects.none())

    class Meta:
        model = CustomerOrderRequestItem
        fields = ("product", "quantity")
        widgets = {"quantity": forms.NumberInput(attrs={"min": "1", "step": "1"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_product_id = self.instance.product_id if self.instance.pk else None
        product_filter = Q(active=True)
        if self._original_product_id:
            product_filter |= Q(pk=self._original_product_id)
        self.fields["product"].queryset = Product.objects.filter(product_filter).order_by(
            "category", "name"
        )

    def clean_product(self) -> Product:
        product = self.cleaned_data["product"]
        if not product.active and product.pk != self._original_product_id:
            raise forms.ValidationError("O produto selecionado está inativo.")
        return product

    def save(self, commit: bool = True) -> CustomerOrderRequestItem:
        item = super().save(commit=False)
        item.unit_price = Decimal(item.product.unit_price)
        if commit:
            item.save()
        return item


class BaseCustomerRequestItemFormSet(BaseInlineFormSet):
    def clean(self) -> None:
        super().clean()
        if any(self.errors):
            return

        product_ids: set[object] = set()
        valid_items = 0
        for form in self.forms:
            cleaned = getattr(form, "cleaned_data", None)
            if not cleaned or cleaned.get("DELETE"):
                continue
            product = cleaned.get("product")
            quantity = cleaned.get("quantity")
            if not product and not quantity:
                continue
            if not product or not quantity:
                raise forms.ValidationError("Preencha produto e quantidade em cada item utilizado.")
            if product.pk in product_ids:
                raise forms.ValidationError(
                    "O mesmo produto não pode aparecer duas vezes na solicitação."
                )
            product_ids.add(product.pk)
            valid_items += 1

        if valid_items < 1:
            raise forms.ValidationError("Adicione ao menos um item válido.")


CustomerRequestItemFormSet = inlineformset_factory(
    CustomerOrderRequest,
    CustomerOrderRequestItem,
    form=CustomerRequestItemForm,
    formset=BaseCustomerRequestItemFormSet,
    fields=("product", "quantity"),
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
    max_num=50,
    validate_max=True,
)


class ReviewReasonForm(forms.Form):
    reason = forms.CharField(
        label="Justificativa",
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
    )

    def clean_reason(self) -> str:
        return self.cleaned_data["reason"].strip()
