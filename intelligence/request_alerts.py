from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from customer_portal.models import CustomerOrderRequest

from .models import AIEvent, AIRecommendation, DataContext

logger = logging.getLogger("emporio.ai")

EVENT_TYPE_REQUEST_SUBMITTED = "request_submitted"
CATEGORY_NEW_REQUEST = "new_request"
SOURCE_TYPE_CUSTOMER_REQUEST = "customer_portal.customerorderrequest"

PENDING_REQUEST_STATUSES = (
    CustomerOrderRequest.Status.SUBMITTED,
    CustomerOrderRequest.Status.IN_REVIEW,
)


@dataclass(frozen=True, slots=True)
class ActiveRequestNotification:
    recommendation_id: str
    request_id: str
    title: str
    summary: str
    reference: str
    company_name: str
    delivery_label: str
    action_url: str
    suggested_action: str
    reason: str
    risk: str
    severity: str
    source_key: str


@dataclass(frozen=True, slots=True)
class RequestNotificationPanel:
    notifications: tuple[ActiveRequestNotification, ...]
    new_count: int
    source_keys: frozenset[str]


def _hash_payload(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _company_ref(company_id) -> str:
    digest = hashlib.sha256(str(company_id).encode()).hexdigest()[:12].upper()
    return f"COMP-{digest}"


def _data_context(customer_request: CustomerOrderRequest) -> str:
    return DataContext.DEMO if customer_request.company.is_demo else DataContext.REAL


def _delivery_label(customer_request: CustomerOrderRequest) -> str:
    date_label = customer_request.delivery_date.strftime("%d/%m/%Y")
    if customer_request.delivery_time is None:
        return f"{date_label} · horário a confirmar"
    return f"{date_label} · {customer_request.delivery_time:%H:%M}"


def _submission_marker(customer_request: CustomerOrderRequest) -> str:
    if customer_request.submitted_at is not None:
        return customer_request.submitted_at.isoformat()
    return f"{customer_request.status}:{customer_request.updated_at.isoformat()}"


def _notification_payload(customer_request: CustomerOrderRequest) -> dict:
    item_quantity = sum(item.quantity for item in customer_request.items.all())
    return {
        "request_ref": customer_request.protocol,
        "company_ref": _company_ref(customer_request.company_id),
        "status": customer_request.status,
        "submitted_at": _submission_marker(customer_request),
        "delivery_date": customer_request.delivery_date.isoformat(),
        "delivery_time": (
            customer_request.delivery_time.isoformat() if customer_request.delivery_time else None
        ),
        "total_amount": str(customer_request.total_amount),
        "item_quantity": item_quantity,
        "delivery_location_present": bool(customer_request.delivery_location_id),
    }


def _create_request_notification(
    customer_request: CustomerOrderRequest,
) -> tuple[AIEvent, AIRecommendation, bool]:
    customer_request = (
        CustomerOrderRequest.objects.select_related("company", "delivery_location")
        .prefetch_related("items")
        .get(pk=customer_request.pk)
    )
    submission_marker = _submission_marker(customer_request)
    idempotency_key = _hash_payload(
        {
            "event_type": EVENT_TYPE_REQUEST_SUBMITTED,
            "source_type": SOURCE_TYPE_CUSTOMER_REQUEST,
            "source_id": str(customer_request.pk),
            "submission_marker": submission_marker,
        }
    )
    payload = _notification_payload(customer_request)
    event, _ = AIEvent.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "event_type": EVENT_TYPE_REQUEST_SUBMITTED,
            "data_context": _data_context(customer_request),
            "source_type": SOURCE_TYPE_CUSTOMER_REQUEST,
            "source_id": str(customer_request.pk),
            "payload": payload,
            "status": AIEvent.Status.COMPLETED,
        },
    )
    recommendation, created = AIRecommendation.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "event": event,
            "category": CATEGORY_NEW_REQUEST,
            "severity": AIRecommendation.Severity.ATTENTION,
            "data_context": event.data_context,
            "source_type": SOURCE_TYPE_CUSTOMER_REQUEST,
            "source_id": str(customer_request.pk),
            "title": f"Nova solicitação {customer_request.protocol}",
            "summary": ("Solicitação enviada pelo Portal B2B e aguardando conferência humana."),
            "action_suggested": (
                "Abrir a solicitação, conferir os dados e decidir o próximo passo."
            ),
            "evidence": {
                **payload,
                "reason": "Uma nova solicitação entrou na fila operacional.",
                "risk": ("A demora na conferência reduz o prazo disponível para atendimento."),
                "analysis_status": "not_required",
            },
            "confidence": Decimal("1.000"),
            "status": AIRecommendation.Status.NEW,
            "expires_at": timezone.now() + timedelta(days=7),
        },
    )
    if created:
        AIRecommendation.objects.filter(
            category=CATEGORY_NEW_REQUEST,
            source_type=SOURCE_TYPE_CUSTOMER_REQUEST,
            source_id=str(customer_request.pk),
            status=AIRecommendation.Status.NEW,
        ).exclude(pk=recommendation.pk).update(
            status=AIRecommendation.Status.EXPIRED,
            updated_at=timezone.now(),
        )
    return event, recommendation, created


def notify_request_submitted(customer_request: CustomerOrderRequest) -> bool:
    if (
        not settings.AI_ACTIVE_ASSISTANT_ENABLED
        or customer_request.status not in PENDING_REQUEST_STATUSES
    ):
        return False
    try:
        with transaction.atomic():
            _, _, created = _create_request_notification(customer_request)
        logger.info(
            "active_assistant_request_notified request_id=%s created=%s",
            customer_request.pk,
            int(created),
        )
        return created
    except Exception:
        logger.exception(
            "active_assistant_request_notification_failed request_id=%s",
            customer_request.pk,
        )
        return False


def build_request_notification_panel(
    user,
    *,
    limit: int = 10,
) -> RequestNotificationPanel:
    from accounts.access import Capability, user_has_capability

    if (
        not settings.AI_ACTIVE_ASSISTANT_ENABLED
        or not user.is_authenticated
        or not user_has_capability(user, Capability.VIEW_REQUESTS)
    ):
        return RequestNotificationPanel((), 0, frozenset())

    recommendations = list(
        AIRecommendation.objects.filter(
            category=CATEGORY_NEW_REQUEST,
            source_type=SOURCE_TYPE_CUSTOMER_REQUEST,
            status=AIRecommendation.Status.NEW,
        )
        .select_related("event")
        .order_by("-created_at")[: max(1, min(limit, 10))]
    )
    request_ids = [recommendation.source_id for recommendation in recommendations]
    customer_requests = {
        str(customer_request.pk): customer_request
        for customer_request in CustomerOrderRequest.objects.filter(
            pk__in=request_ids,
            status__in=PENDING_REQUEST_STATUSES,
        ).select_related("company", "delivery_location")
    }

    notifications: list[ActiveRequestNotification] = []
    source_keys: set[str] = set()
    for recommendation in recommendations:
        customer_request = customer_requests.get(recommendation.source_id)
        if customer_request is None:
            continue
        source_key = f"request:{customer_request.pk}"
        if source_key in source_keys:
            continue
        evidence = recommendation.evidence or {}
        source_keys.add(source_key)
        notifications.append(
            ActiveRequestNotification(
                recommendation_id=str(recommendation.pk),
                request_id=str(customer_request.pk),
                title=recommendation.title,
                summary=recommendation.summary,
                reference=customer_request.protocol,
                company_name=customer_request.company.name,
                delivery_label=_delivery_label(customer_request),
                action_url=reverse(
                    "customer_portal:request-review",
                    kwargs={"pk": customer_request.pk},
                ),
                suggested_action=recommendation.action_suggested,
                reason=str(evidence.get("reason", "")),
                risk=str(evidence.get("risk", "")),
                severity=recommendation.severity,
                source_key=source_key,
            )
        )
    return RequestNotificationPanel(
        notifications=tuple(notifications),
        new_count=len(notifications),
        source_keys=frozenset(source_keys),
    )
