# Generated for MVP-ACESSO-02. Structural only; no production data operation.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserCapabilityOverride",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("capability", models.CharField(max_length=64, verbose_name="capacidade")),
                (
                    "effect",
                    models.CharField(
                        choices=(("allow", "Permitir"), ("deny", "Remover")),
                        max_length=5,
                        verbose_name="efeito",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="capability_overrides",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("capability",),
                "indexes": [
                    models.Index(fields=["user"], name="accounts_override_user_idx")
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "capability"),
                        name="accounts_user_capability_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            capability__in=(
                                "access_dashboard", "view_orders", "create_orders",
                                "edit_orders", "change_order_status", "cancel_orders",
                                "view_requests", "approve_requests", "reject_requests",
                                "request_correction", "view_companies", "manage_companies",
                                "view_products", "manage_products", "view_closings",
                                "review_closings", "export_closings", "view_reports",
                                "view_audit", "access_intelligence", "record_ai_feedback",
                                "manage_attendants", "manage_lower_users",
                                "access_technical_area",
                            )
                        ),
                        name="accounts_override_capability_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(effect__in=("allow", "deny")),
                        name="accounts_override_effect_valid",
                    ),
                ],
            },
        ),
    ]
