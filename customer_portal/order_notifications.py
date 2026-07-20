from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from django.db import transaction
from django.urls import reverse
from django.utils.dateparse import parse_datetime

from intelligence.models import AIEvent, AIRecommendation, DataContext
from orders.models import AuditEvent, Order, OrderStatusHistory
from orders.services import record_audit

logger = logging.getLogger("emporio.requests")

EVENT_TYPE_ORDER_STATUS_CHANGED = "customer_order_status_changed"
SOURCE_TYPE_ORDER_STATUS_HISTORY = "orders.order_status_history"
VIEW_AUDIT_ACTION = "portal.order_status_notification_viewed"


@dataclass(frozen=True)
class CustomerOrderStatusNotification:
    id: object
    order_number: str
    previous_status: str
    new_status: str
    changed_at: object
    message: str
    order_url: str
    viewed_url: str


@dataclass(frozen=True)
class CustomerOrderStatusNotificationPanel:
    notifications: tuple[CustomerOrderStatusNotification, ...]
    unseen_count: int


def _digest(*parts: object) -> str:
    value = ":".join(str(part) for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _message(order: Order, new_status: str) -> str:
    label = Order.Status(new_status).label.lower()
    return f"O estado do seu pedido foi atualizado para {label} pelo Empório Restaurante."


def create_order_status_notification(status_history_id) -> bool:
    history = OrderStatusHistory.objects.select_related("order__company").get(
        pk=status_history_id
    )
    if history.from_status == history.to_status:
        return False

    order = history.order
    key = _digest(
        order.pk,
        order.company_id,
        history.from_status,
        history.to_status,
        history.pk,
    )
    evidence = {
        "order_id": str(order.pk),
        "company_id": str(order.company_id),
        "order_number": order.number,
        "from_status": history.from_status,
        "to_status": history.to_status,
        "changed_at": history.changed_at.isoformat(),
    }
    event, _ = AIEvent.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "event_type": EVENT_TYPE_ORDER_STATUS_CHANGED,
            "data_context": DataContext.REAL,
            "source_type": SOURCE_TYPE_ORDER_STATUS_HISTORY,
            "source_id": str(history.pk),
            "payload": evidence,
            "status": AIEvent.Status.COMPLETED,
        },
    )
    _, created = AIRecommendation.objects.get_or_create(
        idempotency_key=_digest("customer-notification", key),
        defaults={
            "event": event,
            "category": AIRecommendation.Category.SYSTEM,
            "severity": AIRecommendation.Severity.INFO,
            "data_context": DataContext.REAL,
            "source_type": SOURCE_TYPE_ORDER_STATUS_HISTORY,
            "source_id": str(history.pk),
            "title": f"Pedido {order.number} atualizado",
            "summary": _message(order, history.to_status),
            "evidence": evidence,
            "confidence": 1,
            "status": AIRecommendation.Status.NEW,
        },
    )
    return created


def schedule_order_status_notification(status_history_id) -> None:
    def create_safely() -> None:
        try:
            create_order_status_notification(status_history_id)
        except Exception:
            logger.exception("customer_order_status_notification_failed")

    transaction.on_commit(create_safely, robust=True)


def build_order_status_notification_panel(user, company) -> CustomerOrderStatusNotificationPanel:
    viewed_ids = list(
        AuditEvent.objects.filter(
            actor=user,
            action=VIEW_AUDIT_ACTION,
            entity_type=AIRecommendation._meta.label_lower,
        ).values_list("entity_id", flat=True)
    )
    recommendations = (
        AIRecommendation.objects.filter(
            category=AIRecommendation.Category.SYSTEM,
            source_type=SOURCE_TYPE_ORDER_STATUS_HISTORY,
            evidence__company_id=str(company.pk),
        )
        .exclude(pk__in=viewed_ids)
        .order_by("-created_at")[:20]
    )

    notifications = []
    for recommendation in recommendations:
        evidence = recommendation.evidence
        notifications.append(
            CustomerOrderStatusNotification(
                id=recommendation.pk,
                order_number=evidence["order_number"],
                previous_status=Order.Status(evidence["from_status"]).label,
                new_status=Order.Status(evidence["to_status"]).label,
                changed_at=parse_datetime(evidence["changed_at"]),
                message=recommendation.summary,
                order_url=reverse(
                    "customer_portal:order-detail",
                    kwargs={"pk": evidence["order_id"]},
                ),
                viewed_url=reverse(
                    "customer_portal:order-notification-viewed",
                    kwargs={"pk": recommendation.pk},
                ),
            )
        )
    return CustomerOrderStatusNotificationPanel(
        notifications=tuple(notifications),
        unseen_count=len(notifications),
    )


@transaction.atomic
def mark_order_status_notification_viewed(*, notification_id, user, company) -> bool:
    recommendation = AIRecommendation.objects.select_for_update().filter(
        pk=notification_id,
        category=AIRecommendation.Category.SYSTEM,
        source_type=SOURCE_TYPE_ORDER_STATUS_HISTORY,
        evidence__company_id=str(company.pk),
    ).first()
    if recommendation is None:
        return False

    already_viewed = AuditEvent.objects.filter(
        actor=user,
        action=VIEW_AUDIT_ACTION,
        entity_type=recommendation._meta.label_lower,
        entity_id=str(recommendation.pk),
    ).exists()
    if not already_viewed:
        record_audit(
            actor=user,
            action=VIEW_AUDIT_ACTION,
            entity=recommendation,
            payload={
                "order_number": recommendation.evidence["order_number"],
                "from_status": recommendation.evidence["from_status"],
                "to_status": recommendation.evidence["to_status"],
            },
        )
    return True
