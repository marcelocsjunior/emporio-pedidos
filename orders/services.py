from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import AuditEvent, MonthlyClosing, Order, OrderStatusHistory

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Order.Status.PENDING: {Order.Status.RECEIVED, Order.Status.CANCELLED},
    Order.Status.RECEIVED: {Order.Status.IN_PRODUCTION, Order.Status.CANCELLED},
    Order.Status.IN_PRODUCTION: {Order.Status.OUT_FOR_DELIVERY, Order.Status.CANCELLED},
    Order.Status.OUT_FOR_DELIVERY: {Order.Status.DELIVERED, Order.Status.CANCELLED},
    Order.Status.DELIVERED: set(),
    Order.Status.CANCELLED: set(),
}


def record_audit(*, actor, action: str, entity, payload: dict | None = None) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        entity_type=entity._meta.label_lower,
        entity_id=str(entity.pk),
        payload=payload or {},
    )


@transaction.atomic
def change_order_status(
    *,
    order_id,
    new_status: str,
    actor=None,
    reason: str = "",
    idempotency_key: str | None = None,
) -> Order:
    if idempotency_key:
        existing = OrderStatusHistory.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing.order

    order = Order.objects.select_for_update().get(pk=order_id)
    current_status = order.status

    if new_status not in Order.Status.values:
        raise ValidationError({"status": "Status de destino inválido."})
    if new_status == current_status:
        raise ValidationError({"status": "O pedido já está neste status."})
    if new_status not in ALLOWED_TRANSITIONS[current_status]:
        raise ValidationError(
            {"status": f"Transição não permitida: {current_status} → {new_status}."}
        )

    now = timezone.now()
    order.status = new_status
    order.updated_by = actor
    if new_status == Order.Status.DELIVERED:
        order.delivered_at = now
    if new_status == Order.Status.CANCELLED:
        order.cancelled_at = now
    order.save(update_fields=("status", "updated_by", "delivered_at", "cancelled_at", "updated_at"))

    OrderStatusHistory.objects.create(
        order=order,
        from_status=current_status,
        to_status=new_status,
        reason=reason,
        changed_by=actor,
        idempotency_key=idempotency_key,
    )
    record_audit(
        actor=actor,
        action="order.status_changed",
        entity=order,
        payload={"from": current_status, "to": new_status, "reason": reason},
    )
    return order


def build_order_message(order: Order) -> str:
    return (
        f"Olá, {order.company.name}. Pedido {order.number} confirmado. "
        f"Status atual: {order.get_status_display()}. "
        "Qualquer ajuste, nos avise pelo WhatsApp."
    )


def build_closing_message(closing: MonthlyClosing) -> str:
    month = closing.reference_month.strftime("%m/%Y")
    total = f"R$ {closing.total_amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (
        f"Olá, {closing.company.name}. Segue fechamento de {month}: "
        f"{closing.order_count} pedidos, {closing.item_count} itens, total de {total}. "
        "Ficamos à disposição para conferência."
    )


@transaction.atomic
def generate_monthly_closing(
    *,
    company_id,
    reference_month: date,
    actor=None,
) -> MonthlyClosing:
    normalized_month = reference_month.replace(day=1)
    last_day = monthrange(normalized_month.year, normalized_month.month)[1]
    start = normalized_month
    end = normalized_month.replace(day=last_day)

    existing = (
        MonthlyClosing.objects.select_for_update()
        .filter(
            company_id=company_id,
            reference_month=normalized_month,
        )
        .first()
    )
    if existing and existing.status in {
        MonthlyClosing.Status.VALIDATED,
        MonthlyClosing.Status.INVOICED,
    }:
        raise ValidationError("Fechamento validado ou faturado não pode ser recalculado.")

    orders = Order.objects.filter(
        company_id=company_id,
        delivery_date__range=(start, end),
        status=Order.Status.DELIVERED,
    )
    order_count = orders.count()
    total_amount = orders.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00")
    item_count = orders.aggregate(total=Sum("items__quantity"))["total"] or 0

    closing, _ = MonthlyClosing.objects.update_or_create(
        company_id=company_id,
        reference_month=normalized_month,
        defaults={
            "order_count": order_count,
            "item_count": item_count,
            "total_amount": total_amount,
            "status": MonthlyClosing.Status.TO_REVIEW,
            "generated_by": actor,
        },
    )
    closing.message_snapshot = build_closing_message(closing)
    closing.save(update_fields=("message_snapshot", "updated_at"))
    record_audit(
        actor=actor,
        action="closing.generated",
        entity=closing,
        payload={
            "company_id": str(company_id),
            "reference_month": normalized_month.isoformat(),
            "order_count": order_count,
            "item_count": item_count,
            "total_amount": str(total_amount),
        },
    )
    return closing


def local_day_bounds(value: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(value, time.min), tz),
        timezone.make_aware(datetime.combine(value, time.max), tz),
    )
