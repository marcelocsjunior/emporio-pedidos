from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from orders.models import AuditEvent, MonthlyClosing, Order

from .candidates import _expiration_for, _hash_payload, _prompt_version
from .models import AIAnalysisRun, AIEvent, AIRecommendation, AIUsage
from .privacy import PrivacyBlocked, assert_payload_safe
from .providers import GeminiProvider, ProviderPermanentError, ProviderTransientError

RETRY_DELAYS_MINUTES = (15, 30, 60, 120)


def _create_system_alert(event: AIEvent, *, code: str) -> None:
    key = _hash_payload({"system_alert": str(event.pk), "code": code})
    AIRecommendation.objects.update_or_create(
        idempotency_key=key,
        defaults={
            "event": event,
            "category": AIRecommendation.Category.SYSTEM,
            "severity": AIRecommendation.Severity.CRITICAL,
            "data_context": event.data_context,
            "source_type": "intelligence.aievent",
            "source_id": str(event.pk),
            "title": "Processamento da Central Inteligente requer atenção",
            "summary": f"O evento atingiu o estado final de falha: {code}.",
            "action_suggested": "Administrador: revisar configuração, cota ou conectividade.",
            "evidence": {"event_type": event.event_type, "error_code": code},
            "confidence": 1,
            "status": AIRecommendation.Status.NEW,
            "expires_at": timezone.now() + timedelta(days=30),
        },
    )


def _claim_event() -> AIEvent | None:
    with transaction.atomic():
        event = (
            AIEvent.objects.select_for_update()
            .filter(status=AIEvent.Status.PENDING, next_attempt_at__lte=timezone.now())
            .order_by("next_attempt_at", "created_at")
            .first()
        )
        if event is None:
            return None
        event.status = AIEvent.Status.PROCESSING
        event.attempts += 1
        event.locked_at = timezone.now()
        event.last_error_code = ""
        event.save(
            update_fields=(
                "status",
                "attempts",
                "locked_at",
                "last_error_code",
                "updated_at",
            )
        )
        return event


def _complete_event(event: AIEvent, run: AIAnalysisRun, output: dict) -> AIRecommendation:
    candidate = event.payload["candidate"]
    merged = {
        **candidate,
        "title": output.get("title", candidate["title"]),
        "summary": output.get("summary", candidate["summary"]),
        "action_suggested": output.get(
            "action_suggested",
            candidate.get("action_suggested", ""),
        ),
        "confidence": output.get("confidence", candidate.get("confidence", 0)),
    }
    recommendation, _ = AIRecommendation.objects.get_or_create(
        idempotency_key=event.idempotency_key,
        defaults={
            "event": event,
            "category": merged["category"],
            "severity": merged["severity"],
            "data_context": event.data_context,
            "source_type": event.source_type,
            "source_id": event.source_id,
            "title": merged["title"],
            "summary": merged["summary"],
            "action_suggested": merged.get("action_suggested", ""),
            "evidence": merged["evidence"],
            "confidence": merged.get("confidence", 0),
            "expires_at": _expiration_for(merged["category"]),
        },
    )
    AIRecommendation.objects.filter(
        category=recommendation.category,
        source_type=recommendation.source_type,
        source_id=recommendation.source_id,
    ).exclude(pk=recommendation.pk).exclude(
        status=AIRecommendation.Status.EXPIRED
    ).update(
        status=AIRecommendation.Status.EXPIRED,
        updated_at=timezone.now(),
    )
    event.status = AIEvent.Status.COMPLETED
    event.locked_at = None
    event.save(update_fields=("status", "locked_at", "updated_at"))
    run.status = AIAnalysisRun.Status.COMPLETED
    run.structured_output = output
    run.finished_at = timezone.now()
    run.save(update_fields=("status", "structured_output", "finished_at"))
    return recommendation


def process_next_event() -> AIRecommendation | None:
    event = _claim_event()
    if event is None:
        return None

    prompt = _prompt_version()
    run_sequence = AIAnalysisRun.objects.filter(event=event).count() + 1
    run = AIAnalysisRun.objects.create(
        event=event,
        provider="deterministic",
        model_name="",
        prompt_version=prompt.version,
        input_hash=_hash_payload(event.payload),
        sanitized_input=event.payload,
        idempotency_key=f"{event.idempotency_key}:run:{run_sequence}",
    )
    forbidden_terms: tuple[str, ...] = ()
    try:
        assert_payload_safe(event.payload, forbidden_terms=forbidden_terms)
        candidate = event.payload["candidate"]
        output = {
            "title": candidate["title"],
            "summary": candidate["summary"],
            "action_suggested": candidate.get("action_suggested", ""),
            "confidence": candidate.get("confidence", 0),
        }
        if settings.AI_ENABLED:
            result = GeminiProvider().generate(
                payload=event.payload,
                prompt_version=prompt.version,
            )
            output = result.output
            assert_payload_safe(output, forbidden_terms=forbidden_terms)
            run.provider = "gemini"
            run.model_name = settings.GEMINI_MODEL
            run.latency_ms = result.latency_ms
            run.prompt_tokens = result.prompt_tokens
            run.output_tokens = result.output_tokens
            AIUsage.objects.create(
                run=run,
                provider="gemini",
                model_name=settings.GEMINI_MODEL,
                prompt_tokens=result.prompt_tokens,
                output_tokens=result.output_tokens,
                request_count=1,
                free_tier=True,
            )
        return _complete_event(event, run, output)
    except PrivacyBlocked as exc:
        event.status = AIEvent.Status.BLOCKED
        event.last_error_code = str(exc)[:80]
        event.locked_at = None
        event.save(
            update_fields=("status", "last_error_code", "locked_at", "updated_at")
        )
        run.status = AIAnalysisRun.Status.BLOCKED
        run.error_code = event.last_error_code
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "error_code", "finished_at"))
        _create_system_alert(event, code=event.last_error_code)
        return None
    except ProviderTransientError as exc:
        code = exc.code[:80]
        run.status = AIAnalysisRun.Status.FAILED
        run.error_code = code
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "error_code", "finished_at"))
        if event.attempts < settings.AI_MAX_ATTEMPTS:
            delay_index = min(event.attempts - 1, len(RETRY_DELAYS_MINUTES) - 1)
            event.status = AIEvent.Status.PENDING
            event.next_attempt_at = timezone.now() + timedelta(
                minutes=RETRY_DELAYS_MINUTES[delay_index]
            )
        else:
            event.status = AIEvent.Status.FAILED
        event.last_error_code = code
        event.locked_at = None
        event.save(
            update_fields=(
                "status",
                "next_attempt_at",
                "last_error_code",
                "locked_at",
                "updated_at",
            )
        )
        if event.status == AIEvent.Status.FAILED:
            _create_system_alert(event, code=code)
        return None
    except ProviderPermanentError as exc:
        code = exc.code[:80]
        event.status = AIEvent.Status.FAILED
        event.last_error_code = code
        event.locked_at = None
        event.save(
            update_fields=("status", "last_error_code", "locked_at", "updated_at")
        )
        run.status = AIAnalysisRun.Status.FAILED
        run.error_code = code
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "error_code", "finished_at"))
        _create_system_alert(event, code=code)
        return None


def recover_stale_events(*, older_than_minutes: int = 10) -> int:
    now = timezone.now()
    cutoff = now - timedelta(minutes=max(1, older_than_minutes))
    stale_ids = list(
        AIEvent.objects.filter(
            status=AIEvent.Status.PROCESSING,
            locked_at__lt=cutoff,
        ).values_list("pk", flat=True)
    )
    if not stale_ids:
        return 0
    with transaction.atomic():
        AIAnalysisRun.objects.filter(
            event_id__in=stale_ids,
            status=AIAnalysisRun.Status.PROCESSING,
        ).update(
            status=AIAnalysisRun.Status.FAILED,
            error_code="worker_interrupted",
            finished_at=now,
        )
        return AIEvent.objects.filter(pk__in=stale_ids).update(
            status=AIEvent.Status.PENDING,
            next_attempt_at=now,
            locked_at=None,
            last_error_code="stale_lock_recovered",
            updated_at=now,
        )


def process_available_events(*, limit: int = 20) -> int:
    processed = 0
    for _ in range(max(0, limit)):
        event_exists = AIEvent.objects.filter(
            status=AIEvent.Status.PENDING,
            next_attempt_at__lte=timezone.now(),
        ).exists()
        if not event_exists:
            break
        process_next_event()
        processed += 1
    return processed


def expire_stale_recommendations() -> int:
    now = timezone.now()
    expired = AIRecommendation.objects.filter(
        expires_at__isnull=False,
        expires_at__lte=now,
    ).exclude(status=AIRecommendation.Status.EXPIRED)
    count = expired.update(status=AIRecommendation.Status.EXPIRED, updated_at=now)

    delay_recommendations = AIRecommendation.objects.filter(
        category=AIRecommendation.Category.DELAY,
        status__in=(AIRecommendation.Status.NEW, AIRecommendation.Status.VIEWED),
    )
    for recommendation in delay_recommendations:
        order = Order.objects.filter(pk=recommendation.source_id).only("status").first()
        if order and order.status in (Order.Status.DELIVERED, Order.Status.CANCELLED):
            recommendation.status = AIRecommendation.Status.EXPIRED
            recommendation.save(update_fields=("status", "updated_at"))
            count += 1

    closing_recommendations = AIRecommendation.objects.filter(
        category=AIRecommendation.Category.CLOSING,
        status__in=(AIRecommendation.Status.NEW, AIRecommendation.Status.VIEWED),
    )
    for recommendation in closing_recommendations:
        closing = MonthlyClosing.objects.filter(pk=recommendation.source_id).only("status").first()
        if closing and closing.status in (
            MonthlyClosing.Status.VALIDATED,
            MonthlyClosing.Status.INVOICED,
        ):
            recommendation.status = AIRecommendation.Status.EXPIRED
            recommendation.save(update_fields=("status", "updated_at"))
            count += 1
    return count


def audit_manual_enqueue(*, actor, created: dict[str, int]) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor,
        action="intelligence.manual_enqueue",
        entity_type="intelligence.central",
        entity_id=str(actor.pk),
        payload={"created": created},
    )
