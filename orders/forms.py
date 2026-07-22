from __future__ import annotations

from decimal import Decimal

from django import forms
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory

from customer_portal.models import CustomerDeliveryLocation

from .company_imports import MAX_FILE_SIZE, SUPPORTED_FIELDS
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
            "entity_type",
            "document",
            "responsible_name",
            "phone",
            "email",
            "address",
            "city",
            "state",
            "postal_code",
            "customer_type",
            "payment_terms",
            "source_system",
            "external_id",
            "is_demo",
            "notes",
        )
        widgets = {
            "document": forms.TextInput(attrs={"inputmode": "numeric"}),
            "postal_code": forms.TextInput(attrs={"inputmode": "numeric"}),
            "state": forms.TextInput(attrs={"maxlength": "2"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["entity_type"].required = False

    def clean_entity_type(self) -> str:
        return self.cleaned_data.get("entity_type") or Company.EntityType.COMPANY

    def clean_name(self) -> str:
        name = self.cleaned_data["name"].strip()
        duplicate = Company.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("Já existe uma empresa cadastrada com este nome.")
        return name

    def clean_email(self) -> str:
        return self.cleaned_data.get("email", "").strip().lower()

    def clean_state(self) -> str:
        return self.cleaned_data.get("state", "").strip().upper()

    def clean_source_system(self) -> str:
        return self.cleaned_data.get("source_system", "").strip().lower()

    def clean_external_id(self) -> str:
        return self.cleaned_data.get("external_id", "").strip()


class CustomerDeliveryLocationForm(OperationalModelForm):
    class Meta:
        model = CustomerDeliveryLocation
        fields = ("label", "address", "city")

    def __init__(self, *args, company, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)

    def clean_label(self) -> str:
        label = self.cleaned_data["label"].strip()
        duplicate = CustomerDeliveryLocation.objects.filter(
            company=self.company, label__iexact=label
        ).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("Já existe um local com esta identificação para a empresa.")
        return label

    def clean_address(self) -> str:
        return self.cleaned_data["address"].strip()

    def clean_city(self) -> str:
        return self.cleaned_data.get("city", "").strip()


class CompanyImportUploadForm(forms.Form):
    file = forms.FileField(label="Arquivo CSV ou XML")
    allow_reupload = forms.BooleanField(
        required=False,
        label="Confirmo o reenvio deste arquivo já processado anteriormente",
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > MAX_FILE_SIZE:
            raise forms.ValidationError("O arquivo excede o limite de 2 MB.")
        return upload


class CompanyImportMappingForm(forms.Form):
    def __init__(self, *args, headers: list[str], **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "Ignorar")] + [
            (field, field.replace("_", " ").title()) for field in SUPPORTED_FIELDS
        ]
        for index, header in enumerate(headers):
            initial = header.strip().lower() if header.strip().lower() in SUPPORTED_FIELDS else ""
            self.fields[f"field_{index}"] = forms.ChoiceField(
                label=header, choices=choices, required=False, initial=initial
            )

    def mapping(self, headers: list[str]) -> dict[str, str]:
        return {
            header: self.cleaned_data.get(f"field_{index}", "")
            for index, header in enumerate(headers)
        }


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
