from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as datetime_time
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from orders.models import Order

from .models import (
    AIAnalysisRun,
    AIEvent,
    AIPromptVersion,
    AIRecommendation,
    AIUsage,
    DataContext,
)
from .privacy import PrivacyBlocked, assert_payload_safe, sanitize_text
from .providers import ProviderPermanentError, ProviderTransientError

logger = logging.getLogger("emporio.ai")

EVENT_TYPE_ORDER_CREATED = "order_created"
CATEGORY_NEW_ORDER = "new_order"
SOURCE_TYPE_ORDER = "orders.order"

ACTION_CHECK_AND_RECEIVE = "CONFERIR_E_REGISTRAR_RECEBIMENTO"
ACTION_CHECK_DUPLICATE = "VERIFICAR_POSSIVEL_DUPLICIDADE"
ACTION_VALIDATE_DELIVERY = "VALIDAR_DADOS_DE_ENTREGA"
ACTION_PRIORITIZE_PREPARATION = "PRIORIZAR_PREPARACAO"
ACTION_MONITOR = "ACOMPANHAR_SEM_URGENCIA"

ACTION_LABELS = {
    ACTION_CHECK_AND_RECEIVE: "Conferir o pedido e registrar o recebimento.",
    ACTION_CHECK_DUPLICATE: "Verificar possível duplicidade antes de avançar.",
    ACTION_VALIDATE_DELIVERY: "Validar os dados de entrega do pedido.",
    ACTION_PRIORITIZE_PREPARATION: "Priorizar a preparação deste pedido.",
    ACTION_MONITOR: "Acompanhar o pedido sem urgência imediata.",
}

ACTIVE_ORDER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 320},
        "action_code": {"type": "string", "enum": list(ACTION_LABELS)},
        "reason": {"type": "string", "maxLength": 320},
        "risk": {"type": "string", "maxLength": 240},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["summary", "action_code", "reason", "risk", "confidence"],
    "additionalProperties": False,
}

ACTIVE_ORDER_SYSTEM_PROMPT = """Você assessora o operador do Empório Pedidos.
Analise somente as evidências sanitizadas recebidas e seja objetivo.
Escolha exatamente um action_code permitido pelo schema.
Não invente nomes, contatos, endereços, capacidade produtiva ou fatos ausentes.
Não autorize, cancele, altere status, envie mensagens ou execute qualquer ação.
Resumo, motivo e risco devem ser curtos, em português brasileiro.
Retorne somente JSON aderente ao schema fornecido.
"""

RETRY_DELAYS_MINUTES = (1, 2, 5, 10)


@dataclass(frozen=True, slots=True)
class ActiveOrderNotification:
    recommendation_id: str
    order_id: str
    title: str
    summary: str
    reference: str
    company_name: str
    delivery_label: str
    action_url: str
    suggested_action: str
    reason: str
    risk: str
    confidence_label: str
    analysis_status: str
    severity: str
    source_key: str


@dataclass(frozen=True, slots=True)
class ActiveNotificationPanel:
    notifications: tuple[ActiveOrderNotification, ...]
    new_count: int
    source_keys: frozenset[str]


def _hash_payload(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _company_ref(company_id) -> str:
    return f"COMP-{hashlib.sha256(str(company_id).encode()).hexdigest()[:12].upper()}"


def _data_context(order: Order) -> str:
    return DataContext.DEMO if order.company.is_demo else DataContext.REAL


def _redaction_terms(order: Order) -> tuple[str, ...]:
    company = order.company
    return tuple(
        value
        for value in (
            company.name,
            company.responsible_name,
            company.phone,
            company.address,
            company.city,
            order.delivery_location,
        )
        if value
    )


def _delivery_at(order: Order) -> datetime:
    resolved_time = order.delivery_time or datetime_time.max
    return timezone.make_aware(
        datetime.combine(order.delivery_date, resolved_time),
        timezone.get_current_timezone(),
    )


def _delivery_label(order: Order) -> str:
    date_label = order.delivery_date.strftime("%d/%m/%Y")
    if order.delivery_time is None:
        return f"{date_label} · horário a confirmar"
    return f"{date_label} · {order.delivery_time:%H:%M}"


def _possible_duplicate(order: Order) -> bool:
    return (
        Order.objects.filter(
            company_id=order.company_id,
            delivery_date=order.delivery_date,
            total_amount=order.total_amount,
        )
        .exclude(pk=order.pk)
        .exclude(status=Order.Status.CANCELLED)
        .exists()
    )


def _deterministic_action(
    *,
    duplicate: bool,
    delivery_data_complete: bool,
    minutes_to_delivery: int,
) -> tuple[str, str, str]:
    if duplicate:
        return (
            ACTION_CHECK_DUPLICATE,
            "Existe outro pedido da mesma empresa, data e valor para conferência.",
            "O mesmo pedido pode ter sido registrado mais de uma vez.",
        )
    if not delivery_data_complete:
        return (
            ACTION_VALIDATE_DELIVERY,
            "O pedido não possui horário ou local de entrega completos.",
            "A preparação pode avançar sem uma referência de entrega confirmada.",
        )
    if minutes_to_delivery <= 120:
        return (
            ACTION_PRIORITIZE_PREPARATION,
            "O prazo disponível até a entrega é reduzido.",
            "Há risco de atraso caso o pedido não seja conferido rapidamente.",
        )
    if minutes_to_delivery <= 360:
        return (
            ACTION_CHECK_AND_RECEIVE,
            "O pedido foi criado e ainda precisa ser assumido pela operação.",
            "O início tardio da conferência reduz a margem de preparação.",
        )
    return (
        ACTION_MONITOR,
        "O pedido possui prazo operacional disponível.",
        "Nenhum risco imediato foi identificado pelas regras disponíveis.",
    )


def _build_candidate(order: Order) -> dict:
    order = (
        Order.objects.select_related("company")
        .prefetch_related("items")
        .get(pk=order.pk)
    )
    now = timezone.localtime()
    delivery_at = _delivery_at(order)
    minutes_to_delivery = int((delivery_at - now).total_seconds() // 60)
    duplicate = _possible_duplicate(order)
    delivery_data_complete = bool(order.delivery_time and order.delivery_location.strip())
    action_code, reason, risk = _deterministic_action(
        duplicate=duplicate,
        delivery_data_complete=delivery_data_complete,
        minutes_to_delivery=minutes_to_delivery,
    )
    item_rows = list(order.items.all())
    item_quantity = sum(item.quantity for item in item_rows)
    items = [
        {
            "product_ref": item.product_id.hex,
            "product_name": sanitize_text(item.product_name),
            "quantity": item.quantity,
        }
        for item in item_rows
    ]
    notes = sanitize_text(order.notes, redaction_terms=_redaction_terms(order))
    severity = (
        AIRecommendation.Severity.ATTENTION
        if duplicate or not delivery_data_complete or minutes_to_delivery <= 120
        else AIRecommendation.Severity.INFO
    )
    return {
        "category": CATEGORY_NEW_ORDER,
        "severity": severity,
        "title": f"Novo pedido {order.number}",
        "summary": "Pedido criado. A IA está preparando uma orientação objetiva.",
        "action_suggested": ACTION_LABELS[action_code],
        "confidence": 0,
        "evidence": {
            "analysis_status": "pending",
            "action_code": action_code,
            "reason": reason,
            "risk": risk,
            "order_ref": order.number,
            "company_ref": _company_ref(order.company_id),
            "status": order.status,
            "order_date": order.order_date.isoformat(),
            "delivery_date": order.delivery_date.isoformat(),
            "delivery_time": order.delivery_time.isoformat() if order.delivery_time else None,
            "minutes_to_delivery": minutes_to_delivery,
            "total_amount": str(order.total_amount),
            "item_quantity": item_quantity,
            "items": items,
            "delivery_location_present": bool(order.delivery_location.strip()),
            "possible_duplicate": duplicate,
            "notes_sanitized": notes,
        },
    }


def _fallback_candidate(order: Order, *, reason: str) -> dict:
    delivery_at = _delivery_at(order)
    minutes_to_delivery = int((delivery_at - timezone.localtime()).total_seconds() // 60)
    action_code = ACTION_CHECK_AND_RECEIVE
    return {
        "category": CATEGORY_NEW_ORDER,
        "severity": AIRecommendation.Severity.ATTENTION,
        "title": f"Novo pedido {order.number}",
        "summary": "Pedido criado. A análise detalhada foi reduzida por proteção de dados.",
        "action_suggested": ACTION_LABELS[action_code],
        "confidence": 0,
        "evidence": {
            "analysis_status": "pending",
            "action_code": action_code,
            "reason": "Conferir o pedido diretamente no fluxo operacional.",
            "risk": "A análise automatizada dispõe de contexto reduzido.",
            "privacy_fallback": reason,
            "order_ref": order.number,
            "company_ref": _company_ref(order.company_id),
            "status": order.status,
            "delivery_date": order.delivery_date.isoformat(),
            "delivery_time": order.delivery_time.isoformat() if order.delivery_time else None,
            "minutes_to_delivery": minutes_to_delivery,
            "total_amount": str(order.total_amount),
            "item_quantity": order.items.count(),
            "items": [],
            "delivery_location_present": bool(order.delivery_location.strip()),
            "possible_duplicate": False,
            "notes_sanitized": "",
        },
    }


def _active_prompt_version() -> AIPromptVersion:
    prompt, _ = AIPromptVersion.objects.get_or_create(
        key="active-order-assistant",
        version=settings.AI_ACTIVE_ASSISTANT_PROMPT_VERSION,
        defaults={
            "system_prompt": ACTIVE_ORDER_SYSTEM_PROMPT,
            "response_schema": ACTIVE_ORDER_RESPONSE_SCHEMA,
            "active": True,
        },
    )
    return prompt


def _create_notification(order: Order) -> tuple[AIEvent, AIRecommendation, bool]:
    prompt = _active_prompt_version()
    try:
        candidate = _build_candidate(order)
        payload = {
            "candidate": candidate,
            "prompt_version": prompt.version,
        }
        assert_payload_safe(payload)
    except PrivacyBlocked as exc:
        candidate = _fallback_candidate(order, reason=str(exc))
        payload = {
            "candidate": candidate,
            "prompt_version": prompt.version,
        }
        assert_payload_safe(payload)

    idempotency_key = _hash_payload(
        {
            "event_type": EVENT_TYPE_ORDER_CREATED,
            "source_type": SOURCE_TYPE_ORDER,
            "source_id": str(order.pk),
        }
    )
    event, created = AIEvent.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "event_type": EVENT_TYPE_ORDER_CREATED,
            "data_context": _data_context(order),
            "source_type": SOURCE_TYPE_ORDER,
            "source_id": str(order.pk),
            "payload": payload,
        },
    )
    recommendation, _ = AIRecommendation.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "event": event,
            "category": CATEGORY_NEW_ORDER,
            "severity": candidate["severity"],
            "data_context": event.data_context,
            "source_type": SOURCE_TYPE_ORDER,
            "source_id": str(order.pk),
            "title": candidate["title"],
            "summary": candidate["summary"],
            "action_suggested": candidate["action_suggested"],
            "evidence": candidate["evidence"],
            "confidence": candidate["confidence"],
            "status": AIRecommendation.Status.NEW,
            "expires_at": timezone.now() + timedelta(days=7),
        },
    )
    return event, recommendation, created


def notify_order_created(order: Order) -> bool:
    if not settings.AI_ACTIVE_ASSISTANT_ENABLED:
        return False
    try:
        with transaction.atomic():
            _, _, created = _create_notification(order)
        logger.info(
            "active_assistant_order_notified order_id=%s created=%s",
            order.pk,
            int(created),
        )
        return created
    except Exception:
        logger.exception("active_assistant_notification_failed order_id=%s", order.pk)
        return False


def _validated_provider_output(value: dict) -> dict:
    required = {"summary", "action_code", "reason", "risk", "confidence"}
    if not isinstance(value, dict) or set(value) != required:
        raise ProviderPermanentError("invalid_active_assistant_schema")
    if not all(isinstance(value[key], str) for key in required - {"confidence"}):
        raise ProviderPermanentError("invalid_active_assistant_schema")
    action_code = value["action_code"].strip()
    if action_code not in ACTION_LABELS:
        raise ProviderPermanentError("invalid_active_assistant_action")
    try:
        confidence = Decimal(str(value["confidence"]))
    except (InvalidOperation, TypeError) as exc:
        raise ProviderPermanentError("invalid_active_assistant_confidence") from exc
    if confidence < 0 or confidence > 1:
        raise ProviderPermanentError("invalid_active_assistant_confidence")
    output = {
        "summary": value["summary"].strip()[:320],
        "action_code": action_code,
        "reason": value["reason"].strip()[:320],
        "risk": value["risk"].strip()[:240],
        "confidence": float(confidence),
    }
    assert_payload_safe(output)
    return output


class ActiveOrderGeminiProvider:
    provider_name = "gemini"

    def generate(self, *, payload: dict, prompt_version: str) -> tuple[dict, int, int, int]:
        api_key = settings.GEMINI_API_KEY.strip()
        if not api_key:
            raise ProviderPermanentError("api_key_not_configured")
        endpoint = settings.GEMINI_API_URL.format(model=settings.GEMINI_MODEL)
        prompt = (
            f"Versão do prompt: {prompt_version}\n"
            f"Instruções:\n{ACTIVE_ORDER_SYSTEM_PROMPT}\n"
            "Evidências sanitizadas:\n"
            f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        )
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 500,
                "responseMimeType": "application/json",
                "responseJsonSchema": ACTIVE_ORDER_RESPONSE_SCHEMA,
            },
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(
                request,
                timeout=settings.AI_TIMEOUT_SECONDS,
            ) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code < 600:
                raise ProviderTransientError(f"http_{exc.code}") from None
            raise ProviderPermanentError(f"http_{exc.code}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise ProviderTransientError("network_or_decode_error") from None

        try:
            parts = response_data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
            output = _validated_provider_output(json.loads(text))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise ProviderPermanentError("invalid_provider_response") from None

        usage = response_data.get("usageMetadata", {})
        return (
            output,
            max(0, int((time.monotonic() - started) * 1000)),
            int(usage.get("promptTokenCount", 0) or 0),
            int(usage.get("candidatesTokenCount", 0) or 0),
        )


def _claim_active_event() -> AIEvent | None:
    with transaction.atomic():
        event = (
            AIEvent.objects.select_for_update()
            .filter(
                event_type=EVENT_TYPE_ORDER_CREATED,
                status=AIEvent.Status.PENDING,
                next_attempt_at__lte=timezone.now(),
            )
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


def _deterministic_output(event: AIEvent) -> dict:
    candidate = event.payload["candidate"]
    evidence = candidate["evidence"]
    return {
        "summary": candidate["summary"],
        "action_code": evidence["action_code"],
        "reason": evidence["reason"],
        "risk": evidence["risk"],
        "confidence": 1.0,
    }


def _complete_active_event(
    event: AIEvent,
    run: AIAnalysisRun,
    output: dict,
) -> AIRecommendation:
    candidate = event.payload["candidate"]
    evidence = {
        **candidate["evidence"],
        "analysis_status": "completed",
        "action_code": output["action_code"],
        "reason": output["reason"],
        "risk": output["risk"],
    }
    with transaction.atomic():
        recommendation, _ = AIRecommendation.objects.update_or_create(
            idempotency_key=event.idempotency_key,
            defaults={
                "event": event,
                "category": CATEGORY_NEW_ORDER,
                "severity": candidate["severity"],
                "data_context": event.data_context,
                "source_type": SOURCE_TYPE_ORDER,
                "source_id": event.source_id,
                "title": candidate["title"],
                "summary": output["summary"],
                "action_suggested": ACTION_LABELS[output["action_code"]],
                "evidence": evidence,
                "confidence": output["confidence"],
                "expires_at": timezone.now() + timedelta(days=7),
            },
        )
        event.status = AIEvent.Status.COMPLETED
        event.locked_at = None
        event.save(update_fields=("status", "locked_at", "updated_at"))
        run.status = AIAnalysisRun.Status.COMPLETED
        run.structured_output = output
        run.finished_at = timezone.now()
        run.save(update_fields=("status", "structured_output", "finished_at"))
    return recommendation


def _mark_notification_failed(event: AIEvent, *, code: str) -> None:
    recommendation = AIRecommendation.objects.filter(
        idempotency_key=event.idempotency_key,
    ).first()
    if recommendation is None:
        return
    evidence = {
        **recommendation.evidence,
        "analysis_status": "failed",
        "error_code": code,
    }
    recommendation.summary = (
        "Análise da IA temporariamente indisponível. "
        "O pedido permanece disponível para conferência."
    )
    recommendation.action_suggested = ACTION_LABELS[ACTION_CHECK_AND_RECEIVE]
    recommendation.evidence = evidence
    recommendation.save(
        update_fields=("summary", "action_suggested", "evidence", "updated_at")
    )


def _finish_failed_run(run: AIAnalysisRun, *, code: str) -> None:
    run.status = AIAnalysisRun.Status.FAILED
    run.error_code = code[:80]
    run.finished_at = timezone.now()
    run.save(update_fields=("status", "error_code", "finished_at"))


def _process_active_event(event: AIEvent) -> None:
    prompt_version = event.payload.get(
        "prompt_version",
        settings.AI_ACTIVE_ASSISTANT_PROMPT_VERSION,
    )
    run_sequence = AIAnalysisRun.objects.filter(event=event).count() + 1
    run = AIAnalysisRun.objects.create(
        event=event,
        provider="deterministic",
        model_name="",
        prompt_version=prompt_version,
        input_hash=_hash_payload(event.payload),
        sanitized_input=event.payload,
        idempotency_key=f"{event.idempotency_key}:run:{run_sequence}",
    )
    try:
        assert_payload_safe(event.payload)
        output = _deterministic_output(event)
        if settings.AI_ENABLED:
            output, latency_ms, prompt_tokens, output_tokens = (
                ActiveOrderGeminiProvider().generate(
                    payload=event.payload,
                    prompt_version=prompt_version,
                )
            )
            run.provider = "gemini"
            run.model_name = settings.GEMINI_MODEL
            run.latency_ms = latency_ms
            run.prompt_tokens = prompt_tokens
            run.output_tokens = output_tokens
            AIUsage.objects.create(
                run=run,
                provider="gemini",
                model_name=settings.GEMINI_MODEL,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                request_count=1,
                free_tier=True,
            )
        _complete_active_event(event, run, output)
    except PrivacyBlocked as exc:
        code = str(exc)[:80]
        event.status = AIEvent.Status.BLOCKED
        event.last_error_code = code
        event.locked_at = None
        event.save(
            update_fields=("status", "last_error_code", "locked_at", "updated_at")
        )
        _finish_failed_run(run, code=code)
        _mark_notification_failed(event, code=code)
    except ProviderTransientError as exc:
        code = exc.code[:80]
        _finish_failed_run(run, code=code)
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
            _mark_notification_failed(event, code=code)
    except ProviderPermanentError as exc:
        code = exc.code[:80]
        _finish_failed_run(run, code=code)
        event.status = AIEvent.Status.FAILED
        event.last_error_code = code
        event.locked_at = None
        event.save(
            update_fields=("status", "last_error_code", "locked_at", "updated_at")
        )
        _mark_notification_failed(event, code=code)


def process_active_order_events(*, limit: int = 20) -> int:
    processed = 0
    for _ in range(max(0, limit)):
        event = _claim_active_event()
        if event is None:
            break
        _process_active_event(event)
        processed += 1
    return processed


def build_active_notification_panel(user, *, limit: int = 10) -> ActiveNotificationPanel:
    if (
        not settings.AI_ACTIVE_ASSISTANT_ENABLED
        or not user.is_authenticated
        or not user.has_perm("orders.view_order")
    ):
        return ActiveNotificationPanel((), 0, frozenset())

    recommendations = list(
        AIRecommendation.objects.filter(
            category=CATEGORY_NEW_ORDER,
            source_type=SOURCE_TYPE_ORDER,
            status=AIRecommendation.Status.NEW,
        )
        .select_related("event")
        .order_by("-created_at")[: max(1, min(limit, 10))]
    )
    order_ids = [recommendation.source_id for recommendation in recommendations]
    orders = {
        str(order.pk): order
        for order in Order.objects.filter(pk__in=order_ids).select_related("company")
    }

    notifications: list[ActiveOrderNotification] = []
    source_keys: set[str] = set()
    for recommendation in recommendations:
        order = orders.get(recommendation.source_id)
        if order is None:
            continue
        evidence = recommendation.evidence or {}
        confidence = Decimal(recommendation.confidence or 0)
        confidence_label = (
            f"{int(confidence * 100)}%" if evidence.get("analysis_status") == "completed" else ""
        )
        source_key = f"order:{order.pk}"
        source_keys.add(source_key)
        notifications.append(
            ActiveOrderNotification(
                recommendation_id=str(recommendation.pk),
                order_id=str(order.pk),
                title=recommendation.title,
                summary=recommendation.summary,
                reference=order.number,
                company_name=order.company.name,
                delivery_label=_delivery_label(order),
                action_url=reverse("order-detail", kwargs={"pk": order.pk}),
                suggested_action=recommendation.action_suggested,
                reason=str(evidence.get("reason", "")),
                risk=str(evidence.get("risk", "")),
                confidence_label=confidence_label,
                analysis_status=str(evidence.get("analysis_status", "pending")),
                severity=recommendation.severity,
                source_key=source_key,
            )
        )
    return ActiveNotificationPanel(
        notifications=tuple(notifications),
        new_count=len(notifications),
        source_keys=frozenset(source_keys),
    )


def suppress_duplicate_order_cards(panel, source_keys: frozenset[str]):
    if not source_keys:
        return panel
    from .operational_assistant import OperationalAssistantPanel

    cards = tuple(card for card in panel.cards if card.source_key not in source_keys)
    counts = dict(panel.counts)
    for card in panel.cards:
        if card.source_key in source_keys:
            counts[card.kind] = max(0, counts.get(card.kind, 0) - 1)
    removed_total = panel.displayed_count - len(cards)
    return OperationalAssistantPanel(
        cards=cards,
        counts=MappingProxyType(counts),
        total_open=max(0, panel.total_open - removed_total),
        displayed_count=len(cards),
        generated_at=panel.generated_at,
    )
