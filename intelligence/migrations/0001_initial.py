import uuid

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
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
            name="AIEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("delay_risk", "Risco de atraso"),
                            ("duplicate_order", "Possível duplicidade"),
                            ("production_summary", "Resumo de produção"),
                            ("closing_audit", "Auditoria de fechamento"),
                        ],
                        max_length=40,
                        verbose_name="tipo",
                    ),
                ),
                (
                    "data_context",
                    models.CharField(
                        choices=[("real", "Dados reais"), ("demo", "Demonstração")],
                        default="real",
                        max_length=10,
                        verbose_name="contexto dos dados",
                    ),
                ),
                ("source_type", models.CharField(max_length=80, verbose_name="tipo da origem")),
                (
                    "source_id",
                    models.CharField(max_length=180, verbose_name="identificador da origem"),
                ),
                ("payload", models.JSONField(default=dict, verbose_name="entrada minimizada")),
                (
                    "idempotency_key",
                    models.CharField(
                        max_length=64,
                        unique=True,
                        verbose_name="chave de idempotência",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendente"),
                            ("processing", "Processando"),
                            ("completed", "Concluído"),
                            ("failed", "Falhou"),
                            ("blocked", "Bloqueado por privacidade"),
                            ("superseded", "Substituído por versão mais recente"),
                        ],
                        default="pending",
                        max_length=20,
                        verbose_name="status",
                    ),
                ),
                ("attempts", models.PositiveSmallIntegerField(default=0, verbose_name="tentativas")),
                (
                    "next_attempt_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now,
                        verbose_name="próxima tentativa",
                    ),
                ),
                (
                    "locked_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="bloqueado em"),
                ),
                (
                    "last_error_code",
                    models.CharField(blank=True, max_length=80, verbose_name="último código de erro"),
                ),
            ],
            options={
                "verbose_name": "evento de inteligência",
                "verbose_name_plural": "eventos de inteligência",
                "ordering": ("next_attempt_at", "created_at"),
            },
        ),
        migrations.CreateModel(
            name="AIPromptVersion",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("key", models.CharField(max_length=80, verbose_name="identificador")),
                ("version", models.CharField(max_length=80, verbose_name="versão")),
                ("system_prompt", models.TextField(verbose_name="instruções do sistema")),
                (
                    "response_schema",
                    models.JSONField(default=dict, verbose_name="schema de resposta"),
                ),
                ("active", models.BooleanField(default=True, verbose_name="ativo")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
            ],
            options={
                "verbose_name": "versão de prompt",
                "verbose_name_plural": "versões de prompt",
                "ordering": ("key", "-created_at"),
            },
        ),
        migrations.CreateModel(
            name="AIAnalysisRun",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("provider", models.CharField(default="deterministic", max_length=40, verbose_name="provedor")),
                ("model_name", models.CharField(blank=True, max_length=100, verbose_name="modelo")),
                ("prompt_version", models.CharField(max_length=80, verbose_name="versão do prompt")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("processing", "Processando"),
                            ("completed", "Concluída"),
                            ("failed", "Falhou"),
                            ("blocked", "Bloqueada"),
                        ],
                        default="processing",
                        max_length=20,
                        verbose_name="status",
                    ),
                ),
                ("input_hash", models.CharField(max_length=64, verbose_name="hash da entrada")),
                ("sanitized_input", models.JSONField(default=dict, verbose_name="entrada sanitizada")),
                (
                    "structured_output",
                    models.JSONField(blank=True, default=dict, verbose_name="saída estruturada"),
                ),
                ("error_code", models.CharField(blank=True, max_length=80, verbose_name="código de erro")),
                ("latency_ms", models.PositiveIntegerField(default=0, verbose_name="latência em ms")),
                ("prompt_tokens", models.PositiveIntegerField(default=0, verbose_name="tokens de entrada")),
                ("output_tokens", models.PositiveIntegerField(default=0, verbose_name="tokens de saída")),
                (
                    "idempotency_key",
                    models.CharField(max_length=100, unique=True, verbose_name="chave da execução"),
                ),
                ("started_at", models.DateTimeField(auto_now_add=True, verbose_name="iniciada em")),
                (
                    "finished_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="finalizada em"),
                ),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="runs",
                        to="intelligence.aievent",
                        verbose_name="evento",
                    ),
                ),
            ],
            options={
                "verbose_name": "execução de inteligência",
                "verbose_name_plural": "execuções de inteligência",
                "ordering": ("-started_at",),
            },
        ),
        migrations.CreateModel(
            name="AIRecommendation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("delay", "Risco de atraso"),
                            ("duplicate", "Possível duplicidade"),
                            ("production", "Resumo de produção"),
                            ("closing", "Auditoria de fechamento"),
                            ("system", "Sistema de inteligência"),
                        ],
                        max_length=20,
                        verbose_name="categoria",
                    ),
                ),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("info", "Informação"),
                            ("attention", "Atenção"),
                            ("critical", "Crítico"),
                        ],
                        default="info",
                        max_length=20,
                        verbose_name="severidade",
                    ),
                ),
                (
                    "data_context",
                    models.CharField(
                        choices=[("real", "Dados reais"), ("demo", "Demonstração")],
                        default="real",
                        max_length=10,
                        verbose_name="contexto dos dados",
                    ),
                ),
                ("source_type", models.CharField(max_length=80, verbose_name="tipo da origem")),
                (
                    "source_id",
                    models.CharField(max_length=180, verbose_name="identificador da origem"),
                ),
                ("title", models.CharField(max_length=180, verbose_name="título")),
                ("summary", models.TextField(verbose_name="resumo")),
                ("action_suggested", models.TextField(blank=True, verbose_name="ação sugerida")),
                ("evidence", models.JSONField(default=dict, verbose_name="evidências")),
                (
                    "confidence",
                    models.DecimalField(
                        decimal_places=3,
                        default=0,
                        max_digits=4,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(1),
                        ],
                        verbose_name="confiança",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("new", "Nova"),
                            ("viewed", "Visualizada"),
                            ("useful", "Útil"),
                            ("incorrect", "Incorreta"),
                            ("not_applicable", "Não aplicável"),
                            ("expired", "Expirada"),
                        ],
                        default="new",
                        max_length=20,
                        verbose_name="status",
                    ),
                ),
                (
                    "idempotency_key",
                    models.CharField(
                        max_length=64,
                        unique=True,
                        verbose_name="chave de idempotência",
                    ),
                ),
                (
                    "expires_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="expira em"),
                ),
                (
                    "event",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recommendation",
                        to="intelligence.aievent",
                        verbose_name="evento",
                    ),
                ),
            ],
            options={
                "verbose_name": "recomendação da IA",
                "verbose_name_plural": "recomendações da IA",
                "ordering": ("-created_at",),
                "permissions": [
                    ("view_ai_delay", "Pode ver alertas de risco de atraso"),
                    ("view_ai_duplicate", "Pode ver possíveis pedidos duplicados"),
                    ("view_ai_production", "Pode ver resumos de produção"),
                    ("view_ai_finance", "Pode ver auditorias assistidas de fechamento"),
                    ("process_ai_events", "Pode solicitar processamento da Central Inteligente"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AIFeedback",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="atualizado em")),
                (
                    "rating",
                    models.CharField(
                        choices=[
                            ("useful", "Útil"),
                            ("incorrect", "Incorreta"),
                            ("not_applicable", "Não aplicável"),
                        ],
                        max_length=20,
                        verbose_name="avaliação",
                    ),
                ),
                ("notes", models.CharField(blank=True, max_length=255, verbose_name="observação")),
                (
                    "recommendation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feedbacks",
                        to="intelligence.airecommendation",
                        verbose_name="recomendação",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ai_feedbacks",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="operador",
                    ),
                ),
            ],
            options={
                "verbose_name": "avaliação de recomendação",
                "verbose_name_plural": "avaliações de recomendações",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="AIUsage",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("provider", models.CharField(max_length=40, verbose_name="provedor")),
                ("model_name", models.CharField(max_length=100, verbose_name="modelo")),
                ("prompt_tokens", models.PositiveIntegerField(default=0, verbose_name="tokens de entrada")),
                ("output_tokens", models.PositiveIntegerField(default=0, verbose_name="tokens de saída")),
                ("request_count", models.PositiveIntegerField(default=1, verbose_name="requisições")),
                ("free_tier", models.BooleanField(default=True, verbose_name="cota gratuita")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="criado em")),
                (
                    "run",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usage",
                        to="intelligence.aianalysisrun",
                        verbose_name="execução",
                    ),
                ),
            ],
            options={
                "verbose_name": "uso de IA",
                "verbose_name_plural": "usos de IA",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="aievent",
            index=models.Index(fields=["status", "next_attempt_at"], name="intelligenc_status_9b7a28_idx"),
        ),
        migrations.AddIndex(
            model_name="aievent",
            index=models.Index(fields=["event_type", "data_context"], name="intelligenc_event_t_b220fa_idx"),
        ),
        migrations.AddConstraint(
            model_name="aipromptversion",
            constraint=models.UniqueConstraint(
                fields=("key", "version"),
                name="unique_ai_prompt_key_version",
            ),
        ),
        migrations.AddIndex(
            model_name="aianalysisrun",
            index=models.Index(fields=["status", "started_at"], name="intelligenc_status_3e6e56_idx"),
        ),
        migrations.AddIndex(
            model_name="airecommendation",
            index=models.Index(
                fields=["status", "severity", "created_at"],
                name="intelligenc_status_9ea5b7_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="airecommendation",
            index=models.Index(
                fields=["category", "data_context", "created_at"],
                name="intelligenc_categor_133229_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="aifeedback",
            constraint=models.UniqueConstraint(
                fields=("recommendation", "user"),
                name="unique_ai_feedback_per_user",
            ),
        ),
    ]
