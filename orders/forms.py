from __future__ import annotations

from decimal import Decimal

from django import forms
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory

from .models import Company, Order, OrderItem, Product


class OperationalModelForm(forms.ModelForm):
    """Base form with consistent widgets for the operational GUI."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css_class = "form-control"
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = "form-check-input"
            field.widget.attrs["class"] = css_class


class CompanyForm(OperationalModelForm):
    class Meta:
        model = Company
        fields = (
            "name",
            "responsible_name",
            "phone",
            "address",
            "city",
            "customer_type",
            "payment_terms",
            "notes",
        )
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def clean_name(self) -> str:
        name = self.cleaned_data["name"].strip()
        duplicate = Company.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("Já existe uma empresa cadastrada com este nome.")
        return name


class ProductForm(OperationalModelForm):
    class Meta:
        model = Product
        fields = ("name", "category", "unit_price")
        widgets = {
            "unit_price": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
        }

    def clean_name(self) -> str:
        name = self.cleaned_data["name"].strip()
        duplicate = Product.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("Já existe um produto cadastrado com este nome.")
        return name

    def clean_unit_price(self) -> Decimal:
        value = self.cleaned_data["unit_price"]
        if value <= 0:
            raise forms.ValidationError("O valor unitário deve ser maior que zero.")
        return value


class OrderForm(OperationalModelForm):
    class Meta:
        model = Order
        fields = (
            "company",
            "order_date",
            "delivery_date",
            "delivery_time",
            "delivery_location",
            "notes",
        )
        widgets = {
            "order_date": forms.DateInput(attrs={"type": "date"}),
            "delivery_date": forms.DateInput(attrs={"type": "date"}),
            "delivery_time": forms.TimeInput(attrs={"type": "time"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company_filter = Q(active=True)
        if self.instance and self.instance.pk and self.instance.company_id:
            company_filter |= Q(pk=self.instance.company_id)
        self.fields["company"].queryset = Company.objects.filter(company_filter).order_by("name")
        self.fields["delivery_location"].required = True

    def clean_company(self) -> Company:
        company = self.cleaned_data["company"]
        is_current = bool(self.instance.pk and self.instance.company_id == company.pk)
        if not company.active and not is_current:
            raise forms.ValidationError("A empresa selecionada está inativa.")
        return company


class OrderCreateForm(OrderForm):
    creation_key = forms.CharField(widget=forms.HiddenInput, min_length=32, max_length=64)


class ProductChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, product: Product) -> str:
        price = f"{product.unit_price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        category = f" · {product.category}" if product.category else ""
        return f"{product.name}{category} — R$ {price}"


class OrderItemForm(OperationalModelForm):
    product = ProductChoiceField(queryset=Product.objects.none())

    class Meta:
        model = OrderItem
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
        is_current = self._original_product_id == product.pk
        if not product.active and not is_current:
            raise forms.ValidationError("O produto selecionado está inativo.")
        return product

    def save(self, commit: bool = True) -> OrderItem:
        item = super().save(commit=False)
        if not item.pk or self._original_product_id != item.product_id:
            item.unit_price = item.product.unit_price
        if commit:
            item.save()
        return item


class BaseOrderItemFormSet(BaseInlineFormSet):
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
                    "O mesmo produto não pode aparecer duas vezes no pedido."
                )
            product_ids.add(product.pk)
            valid_items += 1

        if valid_items < 1:
            raise forms.ValidationError("Adicione ao menos um item válido ao pedido.")


OrderItemFormSet = inlineformset_factory(
    Order,
    OrderItem,
    form=OrderItemForm,
    formset=BaseOrderItemFormSet,
    fields=("product", "quantity"),
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
    max_num=50,
    validate_max=True,
)
