from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from intelligence.candidates import _hash_payload
from intelligence.engine import process_next_event
from intelligence.models import AIAnalysisRun, AIEvent, AIRecommendation, DataContext
from intelligence.providers import ProviderTransientError
from orders.models import AuditEvent

pytestmark = pytest.mark.django_db


def candidate_payload() -> dict:
    return {
        "candidate": {
            "category": AIRecommendation.Category.DELAY,
            "severity": AIRecommendation.Severity.ATTENTION,
            "title": "Pedido requer atenção",
            "summary": "Pedido próximo do horário de entrega.",
            "action_suggested": "Conferir operação.",
            "confidence": 1.0,
            "evidence": {"order_ref": "PED-TESTE"},
        }
    }


def system_recommendation(event: AIEvent) -> AIRecommendation:
    return AIRecommendation.objects.create(
        event=event,
        category=AIRecommendation.Category.SYSTEM,
        severity=AIRecommendation.Severity.CRITICAL,
        data_context=DataContext.REAL,
        source_type="intelligence.aievent",
        source_id=str(event.pk),
        title="Falha definitiva",
        summary="Limite de tentativas atingido.",
        evidence={"error_code": "http_429"},
        confidence=Decimal("1.000"),
        idempotency_key=_hash_payload(
            {"system_alert": str(event.pk), "code": "http_429"}
        ),
    )


@override_settings(AI_ENABLED=False, AI_MODE="pilot")
def test_retry_sequence_keeps_old_runs_and_can_complete(client):
    user = get_user_model().objects.create_superuser(
        username="ti",
        password="senha-forte-123",
    )
    event = AIEvent.objects.create(
        event_type=AIEvent.EventType.DELAY_RISK,
        data_context=DataContext.REAL,
        source_type="orders.order",
        source_id="retry-cycle",
        payload=candidate_payload(),
        idempotency_key="retry-cycle-event",
        status=AIEvent.Status.FAILED,
        attempts=5,
        last_error_code="http_429",
    )
    AIAnalysisRun.objects.create(
        event=event,
        provider="gemini",
        model_name="gemini-test",
        prompt_version="v1",
        status=AIAnalysisRun.Status.FAILED,
        input_hash="old-input",
        sanitized_input=event.payload,
        error_code="http_429",
        idempotency_key="retry-cycle-event:run:1",
        finished_at=timezone.now(),
    )
    alert = system_recommendation(event)
    client.force_login(user)

    response = client.post(reverse("intelligence:retry", kwargs={"pk": alert.pk}))

    assert response.status_code == 302
    process_next_event()
    event.refresh_from_db()
    alert.refresh_from_db()
    assert event.status == AIEvent.Status.COMPLETED
    assert alert.status == AIRecommendation.Status.EXPIRED
    assert AIAnalysisRun.objects.filter(event=event).count() == 2
    assert AIRecommendation.objects.filter(
        event=event,
        category=AIRecommendation.Category.DELAY,
    ).exists()
    assert AuditEvent.objects.filter(
        action="intelligence.failed_event_requeued",
        actor=user,
    ).exists()


@override_settings(AI_ENABLED=True, AI_MODE="pilot", AI_MAX_ATTEMPTS=5)
def test_repeated_final_failure_reactivates_same_system_alert(monkeypatch):
    event = AIEvent.objects.create(
        event_type=AIEvent.EventType.DELAY_RISK,
        data_context=DataContext.REAL,
        source_type="orders.order",
        source_id="retry-failure",
        payload=candidate_payload(),
        idempotency_key="retry-failure-event",
        status=AIEvent.Status.PENDING,
        attempts=4,
    )
    alert = system_recommendation(event)
    alert.status = AIRecommendation.Status.EXPIRED
    alert.save(update_fields=("status", "updated_at"))

    def fail_generate(*args, **kwargs):
        raise ProviderTransientError("http_429")

    monkeypatch.setattr("intelligence.processor.GeminiProvider.generate", fail_generate)

    process_next_event()

    event.refresh_from_db()
    alert.refresh_from_db()
    assert event.status == AIEvent.Status.FAILED
    assert alert.status == AIRecommendation.Status.NEW
    assert AIRecommendation.objects.filter(
        category=AIRecommendation.Category.SYSTEM,
        source_id=str(event.pk),
    ).count() == 1
