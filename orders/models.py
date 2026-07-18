from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone


def _code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def company_code() -> str:
    return _code("EMP")


def product_code() -> str:
    return _code("PROD")


def order_number() -> str:
    return _code("PED")


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        abstract = True


class Company(TimeStampedModel):
    class CustomerType(models.TextChoices):
        MONTHLY = "monthly", "Mensalista"
        SPOT = "spot", "Avulso"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=20, unique=True, default=company_code, editable=False)
    name = models.CharField("empresa", max_length=180)
    responsible_name = models.CharField("responsável", max_length=150, blank=True)
    phone = models.CharField("telefone", max_length=30, blank=True)
    address = models.CharField("endereço", max_length=255, blank=True)
    city = models.CharField("cidade", max_length=120, blank=True)
    customer_type = models.CharField(
        "tipo de cliente",
        max_length=20,
        choices=CustomerType.choices,
        default=CustomerType.SPOT,
    )
    payment_terms = models.CharField("forma/condição de pagamento", max_length=180, blank=True)
    notes = models.TextField("observações", blank=True)
    active = models.BooleanField("ativo", default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "empresa"
        verbose_name_plural = "empresas"
        indexes = [models.Index(fields=("active", "name"))]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Product(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=20, unique=True, default=product_code, editable=False)
    name = models.CharField("produto", max_length=180)
    category = models.CharField("categoria", max_length=100, blank=True)
    unit_price = models.DecimalField("valor unitário", max_digits=12, decimal_places=2)
    active = models.BooleanField("ativo", default=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "produto"
        verbose_name_plural = "produtos"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="product_unit_price_non_negative",
            )
        ]
        indexes = [models.Index(fields=("active", "name"))]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class Order(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        RECEIVED = "received", "Recebido"
        IN_PRODUCTION = "in_production", "Em produção"
        OUT_FOR_DELIVERY = "out_for_delivery", "Saiu para entrega"
        DELIVERED = "delivered", "Entregue"
        CANCELLED = "cancelled", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=20, unique=True, default=order_number, editable=False)
    creation_key = models.CharField(
        "chave de criação",
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="empresa",
    )
    order_date = models.DateField("data do pedido", default=timezone.localdate)
    delivery_date = models.DateField("data da entrega")
    delivery_time = models.TimeField("horário da entrega", null=True, blank=True)
    status = models.CharField(
        "status",
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
    )
    delivery_location = models.CharField("local da entrega", max_length=255, blank=True)
    notes = models.TextField("observações", blank=True)
    total_amount = models.DecimalField(
        "valor total",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders_created",
        verbose_name="criado por",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders_updated",
        verbose_name="atualizado por",
    )
    delivered_at = models.DateTimeField("entregue em", null=True, blank=True, editable=False)
    cancelled_at = models.DateTimeField("cancelado em", null=True, blank=True, editable=False)

    class Meta:
        ordering = ("-delivery_date", "-delivery_time", "number")
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="order_total_amount_non_negative",
            )
        ]
        indexes = [
            models.Index(fields=("delivery_date", "status")),
            models.Index(fields=("company", "order_date")),
        ]

    def clean(self) -> None:
        super().clean()
        if self.delivery_date and self.order_date and self.delivery_date < self.order_date:
            raise ValidationError({"delivery_date": "A entrega não pode ser anterior ao pedido."})

    def recalculate_total(self) -> Decimal:
        total = self.items.aggregate(total=Sum("line_total"))["total"] or Decimal("0.00")
        total = total.quantize(Decimal("0.01"))
        type(self).objects.filter(pk=self.pk).update(total_amount=total, updated_at=timezone.now())
        self.total_amount = total
        return total

    def __str__(self) -> str:
        return f"{self.number} — {self.company.name}"


class OrderItem(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="pedido",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name="produto",
    )
    product_name = models.CharField("descrição congelada", max_length=180, editable=False)
    quantity = models.PositiveIntegerField("quantidade")
    unit_price = models.DecimalField("valor unitário", max_digits=12, decimal_places=2)
    line_total = models.DecimalField(
        "valor total do item",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
    )

    class Meta:
        ordering = ("created_at",)
        verbose_name = "item do pedido"
        verbose_name_plural = "itens do pedido"
        constraints = [
            models.UniqueConstraint(fields=("order", "product"), name="unique_product_per_order"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="order_item_quantity_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="order_item_unit_price_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(line_total__gte=0),
                name="order_item_line_total_non_negative",
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        if self._state.adding and self.unit_price == Decimal("0.00"):
            self.unit_price = self.product.unit_price
        self.product_name = self.product.name
        self.line_total = (Decimal(self.quantity) * self.unit_price).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
        self.order.recalculate_total()

    def delete(self, *args, **kwargs):
        order = self.order
        result = super().delete(*args, **kwargs)
        order.recalculate_total()
        return result

    def __str__(self) -> str:
        return f"{self.order.number} — {self.product_name} x {self.quantity}"


class OrderStatusHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name="pedido",
    )
    from_status = models.CharField("status anterior", max_length=30, choices=Order.Status.choices)
    to_status = models.CharField("novo status", max_length=30, choices=Order.Status.choices)
    reason = models.CharField("motivo", max_length=255, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_status_changes",
        verbose_name="alterado por",
    )
    changed_at = models.DateTimeField("alterado em", auto_now_add=True)
    idempotency_key = models.CharField(
        "chave de idempotência",
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("-changed_at",)
        verbose_name = "histórico de status"
        verbose_name_plural = "históricos de status"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(from_status=models.F("to_status")),
                name="status_history_must_change",
            )
        ]
        indexes = [models.Index(fields=("order", "changed_at"))]


class MonthlyClosing(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        TO_REVIEW = "to_review", "A conferir"
        VALIDATED = "validated", "Validado"
        INVOICED = "invoiced", "Faturado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="closings",
        verbose_name="empresa",
    )
    reference_month = models.DateField("mês de referência")
    order_count = models.PositiveIntegerField("total de pedidos", default=0)
    item_count = models.PositiveIntegerField("total de itens", default=0)
    total_amount = models.DecimalField(
        "valor total",
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    status = models.CharField(
        "status",
        max_length=20,
        choices=Status.choices,
        default=Status.TO_REVIEW,
    )
    message_snapshot = models.TextField("mensagem do fechamento", blank=True)
    notes = models.TextField("observações", blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closings_generated",
        verbose_name="gerado por",
    )
    validated_at = models.DateTimeField("validado em", null=True, blank=True)
    invoiced_at = models.DateTimeField("faturado em", null=True, blank=True)

    class Meta:
        ordering = ("-reference_month", "company__name")
        verbose_name = "fechamento mensal"
        verbose_name_plural = "fechamentos mensais"
        constraints = [
            models.UniqueConstraint(
                fields=("company", "reference_month"),
                name="unique_company_reference_month",
            ),
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=0),
                name="closing_total_amount_non_negative",
            ),
        ]
        indexes = [models.Index(fields=("reference_month", "status"))]

    def clean(self) -> None:
        super().clean()
        if self.reference_month and self.reference_month.day != 1:
            raise ValidationError(
                {"reference_month": "O mês de referência deve usar o primeiro dia do mês."}
            )

    def __str__(self) -> str:
        return f"{self.company.name} — {self.reference_month:%m/%Y}"


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
        verbose_name="operador",
    )
    action = models.CharField("ação", max_length=100)
    entity_type = models.CharField("tipo da entidade", max_length=100)
    entity_id = models.CharField("identificador da entidade", max_length=100)
    payload = models.JSONField("evidências", default=dict, blank=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "evento de auditoria"
        verbose_name_plural = "eventos de auditoria"
        indexes = [
            models.Index(fields=("entity_type", "entity_id")),
            models.Index(fields=("created_at",)),
        ]

    def __str__(self) -> str:
        return f"{self.action} — {self.entity_type}:{self.entity_id}"
