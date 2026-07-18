from __future__ import annotations

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        abstract = True


class DataContext(models.TextChoices):
    REAL = "real", "Dados reais"
    DEMO = "demo", "Demonstração"


class AIEvent(TimeStampedModel):
    class EventType(models.TextChoices):
        DELAY_RISK = "delay_risk", "Risco de atraso"
        DUPLICATE_ORDER = "duplicate_order", "Possível duplicidade"
        PRODUCTION_SUMMARY = "production_summary", "Resumo de produção"
        CLOSING_AUDIT = "closing_audit", "Auditoria de fechamento"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PROCESSING = "processing", "Processando"
        COMPLETED = "completed", "Concluído"
        FAILED = "failed", "Falhou"
        BLOCKED = "blocked", "Bloqueado por privacidade"
        SUPERSEDED = "superseded", "Substituído por versão mais recente"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField("tipo", max_length=40, choices=EventType.choices)
    data_context = models.CharField(
        "contexto dos dados",
        max_length=10,
        choices=DataContext.choices,
        default=DataContext.REAL,
    )
    source_type = models.CharField("tipo da origem", max_length=80)
    source_id = models.CharField("identificador da origem", max_length=180)
    payload = models.JSONField("entrada minimizada", default=dict)
    idempotency_key = models.CharField("chave de idempotência", max_length=64, unique=True)
    status = models.CharField(
        "status",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    attempts = models.PositiveSmallIntegerField("tentativas", default=0)
    next_attempt_at = models.DateTimeField("próxima tentativa", default=timezone.now)
    locked_at = models.DateTimeField("bloqueado em", null=True, blank=True)
    last_error_code = models.CharField("último código de erro", max_length=80, blank=True)

    class Meta:
        ordering = ("next_attempt_at", "created_at")
        verbose_name = "evento de inteligência"
        verbose_name_plural = "eventos de inteligência"
        indexes = [
            models.Index(fields=("status", "next_attempt_at")),
            models.Index(fields=("event_type", "data_context")),
        ]

    def __str__(self) -> str:
        return f"{self.get_event_type_display()} — {self.source_type}:{self.source_id}"


class AIAnalysisRun(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Processando"
        COMPLETED = "completed", "Concluída"
        FAILED = "failed", "Falhou"
        BLOCKED = "blocked", "Bloqueada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        AIEvent,
        on_delete=models.CASCADE,
        related_name="runs",
        verbose_name="evento",
    )
    provider = models.CharField("provedor", max_length=40, default="deterministic")
    model_name = models.CharField("modelo", max_length=100, blank=True)
    prompt_version = models.CharField("versão do prompt", max_length=80)
    status = models.CharField(
        "status",
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
    )
    input_hash = models.CharField("hash da entrada", max_length=64)
    sanitized_input = models.JSONField("entrada sanitizada", default=dict)
    structured_output = models.JSONField("saída estruturada", default=dict, blank=True)
    error_code = models.CharField("código de erro", max_length=80, blank=True)
    latency_ms = models.PositiveIntegerField("latência em ms", default=0)
    prompt_tokens = models.PositiveIntegerField("tokens de entrada", default=0)
    output_tokens = models.PositiveIntegerField("tokens de saída", default=0)
    idempotency_key = models.CharField("chave da execução", max_length=100, unique=True)
    started_at = models.DateTimeField("iniciada em", auto_now_add=True)
    finished_at = models.DateTimeField("finalizada em", null=True, blank=True)

    class Meta:
        ordering = ("-started_at",)
        verbose_name = "execução de inteligência"
        verbose_name_plural = "execuções de inteligência"
        indexes = [models.Index(fields=("status", "started_at"))]

    def __str__(self) -> str:
        return f"{self.event_id} — tentativa {self.event.attempts}"


class AIRecommendation(TimeStampedModel):
    class Category(models.TextChoices):
        DELAY = "delay", "Risco de atraso"
        DUPLICATE = "duplicate", "Possível duplicidade"
        PRODUCTION = "production", "Resumo de produção"
        CLOSING = "closing", "Auditoria de fechamento"
        SYSTEM = "system", "Sistema de inteligência"

    class Severity(models.TextChoices):
        INFO = "info", "Informação"
        ATTENTION = "attention", "Atenção"
        CRITICAL = "critical", "Crítico"

    class Status(models.TextChoices):
        NEW = "new", "Nova"
        VIEWED = "viewed", "Visualizada"
        USEFUL = "useful", "Útil"
        INCORRECT = "incorrect", "Incorreta"
        NOT_APPLICABLE = "not_applicable", "Não aplicável"
        EXPIRED = "expired", "Expirada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.OneToOneField(
        AIEvent,
        on_delete=models.CASCADE,
        related_name="recommendation",
        verbose_name="evento",
    )
    category = models.CharField("categoria", max_length=20, choices=Category.choices)
    severity = models.CharField(
        "severidade",
        max_length=20,
        choices=Severity.choices,
        default=Severity.INFO,
    )
    data_context = models.CharField(
        "contexto dos dados",
        max_length=10,
        choices=DataContext.choices,
        default=DataContext.REAL,
    )
    source_type = models.CharField("tipo da origem", max_length=80)
    source_id = models.CharField("identificador da origem", max_length=180)
    title = models.CharField("título", max_length=180)
    summary = models.TextField("resumo")
    action_suggested = models.TextField("ação sugerida", blank=True)
    evidence = models.JSONField("evidências", default=dict)
    confidence = models.DecimalField(
        "confiança",
        max_digits=4,
        decimal_places=3,
        default=0,
        validators=(MinValueValidator(0), MaxValueValidator(1)),
    )
    status = models.CharField(
        "status",
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )
    idempotency_key = models.CharField("chave de idempotência", max_length=64, unique=True)
    expires_at = models.DateTimeField("expira em", null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "recomendação da IA"
        verbose_name_plural = "recomendações da IA"
        indexes = [
            models.Index(fields=("status", "severity", "created_at")),
            models.Index(fields=("category", "data_context", "created_at")),
        ]
        permissions = [
            ("view_ai_delay", "Pode ver alertas de risco de atraso"),
            ("view_ai_duplicate", "Pode ver possíveis pedidos duplicados"),
            ("view_ai_production", "Pode ver resumos de produção"),
            ("view_ai_finance", "Pode ver auditorias assistidas de fechamento"),
            ("process_ai_events", "Pode solicitar processamento da Central Inteligente"),
        ]

    def __str__(self) -> str:
        return self.title


class AIFeedback(TimeStampedModel):
    class Rating(models.TextChoices):
        USEFUL = "useful", "Útil"
        INCORRECT = "incorrect", "Incorreta"
        NOT_APPLICABLE = "not_applicable", "Não aplicável"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recommendation = models.ForeignKey(
        AIRecommendation,
        on_delete=models.CASCADE,
        related_name="feedbacks",
        verbose_name="recomendação",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_feedbacks",
        verbose_name="operador",
    )
    rating = models.CharField("avaliação", max_length=20, choices=Rating.choices)
    notes = models.CharField("observação", max_length=255, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "avaliação de recomendação"
        verbose_name_plural = "avaliações de recomendações"
        constraints = [
            models.UniqueConstraint(
                fields=("recommendation", "user"),
                name="unique_ai_feedback_per_user",
            )
        ]

    def __str__(self) -> str:
        return f"{self.recommendation_id} — {self.get_rating_display()}"


class AIPromptVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField("identificador", max_length=80)
    version = models.CharField("versão", max_length=80)
    system_prompt = models.TextField("instruções do sistema")
    response_schema = models.JSONField("schema de resposta", default=dict)
    active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        ordering = ("key", "-created_at")
        verbose_name = "versão de prompt"
        verbose_name_plural = "versões de prompt"
        constraints = [
            models.UniqueConstraint(
                fields=("key", "version"),
                name="unique_ai_prompt_key_version",
            )
        ]

    def __str__(self) -> str:
        return f"{self.key}:{self.version}"


class AIUsage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.OneToOneField(
        AIAnalysisRun,
        on_delete=models.CASCADE,
        related_name="usage",
        verbose_name="execução",
    )
    provider = models.CharField("provedor", max_length=40)
    model_name = models.CharField("modelo", max_length=100)
    prompt_tokens = models.PositiveIntegerField("tokens de entrada", default=0)
    output_tokens = models.PositiveIntegerField("tokens de saída", default=0)
    request_count = models.PositiveIntegerField("requisições", default=1)
    free_tier = models.BooleanField("cota gratuita", default=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "uso de IA"
        verbose_name_plural = "usos de IA"

    def __str__(self) -> str:
        return f"{self.provider}/{self.model_name} — {self.request_count} requisição"
