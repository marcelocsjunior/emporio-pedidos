from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from orders.models import Company, Order, Product


def request_protocol() -> str:
    return f"SOL-{uuid.uuid4().hex[:8].upper()}"


class CustomerPortalAccess(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="customer_portal_access",
        verbose_name="usuário",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="portal_accesses",
        verbose_name="empresa",
    )
    active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ("company__name", "user__username")
        verbose_name = "acesso ao portal"
        verbose_name_plural = "acessos ao portal"
        indexes = [
            models.Index(
                fields=("company", "active"),
                name="portal_access_company_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.company.name}"


class CustomerDeliveryLocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="customer_delivery_locations",
        verbose_name="empresa",
    )
    label = models.CharField("identificação", max_length=120)
    address = models.CharField("endereço", max_length=255)
    city = models.CharField("cidade", max_length=120, blank=True)
    active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ("company__name", "label")
        verbose_name = "local de entrega do cliente"
        verbose_name_plural = "locais de entrega dos clientes"
        constraints = [
            models.UniqueConstraint(
                fields=("company", "label"),
                name="unique_customer_location_label",
            )
        ]
        indexes = [
            models.Index(
                fields=("company", "active"),
                name="portal_location_company_idx",
            )
        ]

    @property
    def full_address(self) -> str:
        return ", ".join(part for part in (self.address, self.city) if part)

    def __str__(self) -> str:
        return f"{self.label} — {self.full_address}"


class CustomerOrderRequest(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        SUBMITTED = "submitted", "Enviada"
        IN_REVIEW = "in_review", "Em análise"
        CORRECTION_REQUESTED = "correction_requested", "Aguardando correção"
        APPROVED = "approved", "Aprovada"
        CONVERTED = "converted", "Convertida em pedido"
        REJECTED = "rejected", "Rejeitada"
        CANCELLED = "cancelled", "Cancelada pelo cliente"
        EXPIRED = "expired", "Expirada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    protocol = models.CharField(
        "protocolo",
        max_length=20,
        unique=True,
        default=request_protocol,
        editable=False,
    )
    creation_key = models.CharField(
        "chave de criação",
        max_length=64,
        unique=True,
        editable=False,
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="customer_order_requests",
        verbose_name="empresa",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="customer_order_requests",
        verbose_name="solicitado por",
    )
    delivery_date = models.DateField("data da entrega")
    delivery_time = models.TimeField("horário da entrega", null=True, blank=True)
    delivery_location = models.ForeignKey(
        CustomerDeliveryLocation,
        on_delete=models.PROTECT,
        related_name="order_requests",
        verbose_name="local de entrega",
    )
    delivery_address_snapshot = models.CharField(
        "endereço congelado",
        max_length=400,
        blank=True,
        editable=False,
    )
    notes = models.TextField("observações", blank=True)
    status = models.CharField(
        "status",
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    total_amount = models.DecimalField(
        "valor total",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
    )
    submitted_at = models.DateTimeField("enviada em", null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customer_requests_reviewed",
        verbose_name="revisada por",
    )
    reviewed_at = models.DateTimeField("revisada em", null=True, blank=True)
    review_notes = models.TextField("retorno do atendimento", blank=True)
    approved_at = models.DateTimeField("aprovada em", null=True, blank=True)
    cancelled_at = models.DateTimeField("cancelada em", null=True, blank=True)
    converted_order = models.OneToOneField(
        Order,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="customer_request",
        verbose_name="pedido gerado",
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "solicitação de pedido"
        verbose_name_plural = "solicitações de pedido"
        permissions = [
            ("review_customerorderrequest", "Pode revisar solicitações de clientes"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="customer_request_total_non_negative",
            )
        ]
        indexes = [
            models.Index(
                fields=("company", "status", "created_at"),
                name="portal_request_company_idx",
            ),
            models.Index(
                fields=("status", "delivery_date"),
                name="portal_request_queue_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.delivery_location_id and self.company_id:
            if self.delivery_location.company_id != self.company_id:
                raise ValidationError(
                    {"delivery_location": "O local de entrega não pertence à empresa vinculada."}
                )

    def recalculate_total(self) -> Decimal:
        total = self.items.aggregate(total=Sum("line_total"))["total"] or Decimal("0.00")
        total = total.quantize(Decimal("0.01"))
        type(self).objects.filter(pk=self.pk).update(
            total_amount=total,
            updated_at=timezone.now(),
        )
        self.total_amount = total
        return total

    def __str__(self) -> str:
        return f"{self.protocol} — {self.company.name}"


class CustomerOrderRequestItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(
        CustomerOrderRequest,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="solicitação",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="customer_request_items",
        verbose_name="produto",
    )
    product_name = models.CharField("descrição congelada", max_length=180, editable=False)
    quantity = models.PositiveIntegerField("quantidade")
    unit_price = models.DecimalField(
        "valor unitário",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
    )
    line_total = models.DecimalField(
        "valor total do item",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ("created_at",)
        verbose_name = "item da solicitação"
        verbose_name_plural = "itens da solicitação"
        constraints = [
            models.UniqueConstraint(
                fields=("request", "product"),
                name="unique_product_per_customer_request",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="customer_request_item_quantity_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="customer_request_item_price_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(line_total__gte=0),
                name="customer_request_item_total_non_negative",
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        self.product_name = self.product.name
        self.line_total = (Decimal(self.quantity) * self.unit_price).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
        self.request.recalculate_total()

    def delete(self, *args, **kwargs):
        customer_request = self.request
        result = super().delete(*args, **kwargs)
        customer_request.recalculate_total()
        return result

    def __str__(self) -> str:
        return f"{self.request.protocol} — {self.product_name} x {self.quantity}"
