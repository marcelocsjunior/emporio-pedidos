import uuid
from decimal import Decimal

import customer_portal.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orders", "0003_company_is_demo"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerDeliveryLocation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("label", models.CharField(max_length=120, verbose_name="identificação")),
                ("address", models.CharField(max_length=255, verbose_name="endereço")),
                ("city", models.CharField(blank=True, max_length=120, verbose_name="cidade")),
                ("active", models.BooleanField(default=True, verbose_name="ativo")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customer_delivery_locations",
                        to="orders.company",
                        verbose_name="empresa",
                    ),
                ),
            ],
            options={
                "verbose_name": "local de entrega do cliente",
                "verbose_name_plural": "locais de entrega dos clientes",
                "ordering": ("company__name", "label"),
                "indexes": [
                    models.Index(
                        fields=["company", "active"],
                        name="portal_location_company_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("company", "label"),
                        name="unique_customer_location_label",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="CustomerPortalAccess",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("active", models.BooleanField(default=True, verbose_name="ativo")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="portal_accesses",
                        to="orders.company",
                        verbose_name="empresa",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customer_portal_access",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="usuário",
                    ),
                ),
            ],
            options={
                "verbose_name": "acesso ao portal",
                "verbose_name_plural": "acessos ao portal",
                "ordering": ("company__name", "user__username"),
                "indexes": [
                    models.Index(
                        fields=["company", "active"],
                        name="portal_access_company_idx",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="CustomerOrderRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "protocol",
                    models.CharField(
                        default=customer_portal.models.request_protocol,
                        editable=False,
                        max_length=20,
                        unique=True,
                        verbose_name="protocolo",
                    ),
                ),
                (
                    "creation_key",
                    models.CharField(editable=False, max_length=64, unique=True, verbose_name="chave de criação"),
                ),
                ("delivery_date", models.DateField(verbose_name="data da entrega")),
                ("delivery_time", models.TimeField(blank=True, null=True, verbose_name="horário da entrega")),
                (
                    "delivery_address_snapshot",
                    models.CharField(blank=True, editable=False, max_length=400, verbose_name="endereço congelado"),
                ),
                ("notes", models.TextField(blank=True, verbose_name="observações")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Rascunho"),
                            ("submitted", "Enviada"),
                            ("in_review", "Em análise"),
                            ("correction_requested", "Aguardando correção"),
                            ("approved", "Aprovada"),
                            ("converted", "Convertida em pedido"),
                            ("rejected", "Rejeitada"),
                            ("cancelled", "Cancelada pelo cliente"),
                            ("expired", "Expirada"),
                        ],
                        default="draft",
                        max_length=30,
                        verbose_name="status",
                    ),
                ),
                (
                    "total_amount",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        editable=False,
                        max_digits=14,
                        verbose_name="valor total",
                    ),
                ),
                ("submitted_at", models.DateTimeField(blank=True, null=True, verbose_name="enviada em")),
                ("reviewed_at", models.DateTimeField(blank=True, null=True, verbose_name="revisada em")),
                ("review_notes", models.TextField(blank=True, verbose_name="retorno do atendimento")),
                ("approved_at", models.DateTimeField(blank=True, null=True, verbose_name="aprovada em")),
                ("cancelled_at", models.DateTimeField(blank=True, null=True, verbose_name="cancelada em")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customer_order_requests",
                        to="orders.company",
                        verbose_name="empresa",
                    ),
                ),
                (
                    "converted_order",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customer_request",
                        to="orders.order",
                        verbose_name="pedido gerado",
                    ),
                ),
                (
                    "delivery_location",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="order_requests",
                        to="customer_portal.customerdeliverylocation",
                        verbose_name="local de entrega",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customer_order_requests",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="solicitado por",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="customer_requests_reviewed",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="revisada por",
                    ),
                ),
            ],
            options={
                "verbose_name": "solicitação de pedido",
                "verbose_name_plural": "solicitações de pedido",
                "ordering": ("-created_at",),
                "permissions": [("review_customerorderrequest", "Pode revisar solicitações de clientes")],
                "indexes": [
                    models.Index(
                        fields=["company", "status", "created_at"],
                        name="portal_request_company_idx",
                    ),
                    models.Index(
                        fields=["status", "delivery_date"],
                        name="portal_request_queue_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("total_amount__gte", 0)),
                        name="customer_request_total_non_negative",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="CustomerOrderRequestItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("product_name", models.CharField(editable=False, max_length=180, verbose_name="descrição congelada")),
                ("quantity", models.PositiveIntegerField(verbose_name="quantidade")),
                (
                    "unit_price",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        editable=False,
                        max_digits=12,
                        verbose_name="valor unitário",
                    ),
                ),
                (
                    "line_total",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        editable=False,
                        max_digits=14,
                        verbose_name="valor total do item",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customer_request_items",
                        to="orders.product",
                        verbose_name="produto",
                    ),
                ),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="customer_portal.customerorderrequest",
                        verbose_name="solicitação",
                    ),
                ),
            ],
            options={
                "verbose_name": "item da solicitação",
                "verbose_name_plural": "itens da solicitação",
                "ordering": ("created_at",),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("request", "product"),
                        name="unique_product_per_customer_request",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0)),
                        name="customer_request_item_quantity_gt_zero",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("unit_price__gte", 0)),
                        name="customer_request_item_price_non_negative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("line_total__gte", 0)),
                        name="customer_request_item_total_non_negative",
                    ),
                ],
            },
        ),
    ]
