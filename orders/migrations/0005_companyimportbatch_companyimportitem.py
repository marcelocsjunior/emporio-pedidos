import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orders", "0004_company_customer_identity"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyImportBatch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("executed_at", models.DateTimeField(blank=True, null=True)),
                ("original_filename", models.CharField(max_length=255)),
                ("file_hash", models.CharField(db_index=True, max_length=64)),
                ("file_format", models.CharField(choices=[("csv", "CSV"), ("xml", "XML")], max_length=3)),
                ("separator", models.CharField(blank=True, max_length=1)),
                ("encoding", models.CharField(blank=True, max_length=30)),
                ("mapping", models.JSONField(blank=True, default=dict)),
                ("total_count", models.PositiveIntegerField(default=0)),
                ("valid_count", models.PositiveIntegerField(default=0)),
                ("invalid_count", models.PositiveIntegerField(default=0)),
                ("duplicate_count", models.PositiveIntegerField(default=0)),
                ("ignored_count", models.PositiveIntegerField(default=0)),
                ("imported_count", models.PositiveIntegerField(default=0)),
                ("status", models.CharField(choices=[("uploaded", "Enviado"), ("previewed", "Pré-visualizado"), ("completed", "Concluído"), ("failed", "Falhou"), ("rolled_back", "Desfeito"), ("rollback_blocked", "Rollback bloqueado")], default="uploaded", max_length=30)),
                ("final_message", models.CharField(blank=True, max_length=500)),
                ("rollback_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="company_import_batches", to=settings.AUTH_USER_MODEL)),
                ("rollback_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="company_import_rollbacks", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(
            model_name="companyimportbatch",
            index=models.Index(fields=["file_hash", "status"], name="orders_comp_file_ha_131a92_idx"),
        ),
        migrations.CreateModel(
            name="CompanyImportItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("source_row", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="orders.companyimportbatch")),
                ("company", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="import_item", to="orders.company")),
            ],
            options={"ordering": ("source_row",)},
        ),
        migrations.AddConstraint(
            model_name="companyimportitem",
            constraint=models.UniqueConstraint(fields=("batch", "source_row"), name="unique_import_batch_source_row"),
        ),
    ]
