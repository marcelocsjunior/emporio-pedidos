from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
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

ORDER_EDITABLE_STATUSES = {Order.Status.PENDING, Order.Status.RECEIVED}


def record_audit(*, actor, action: str, entity, payload: dict | None = None) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        entity_type=entity._meta.label_lower,
        entity_id=str(entity.pk),
        payload=payload or {},
    )


def _order_snapshot(order: Order) -> dict[str, str]:
    return {
        "company_id": str(order.company_id),
        "order_date": order.order_date.isoformat(),
        "delivery_date": order.delivery_date.isoformat(),
        "delivery_time": order.delivery_time.isoformat() if order.delivery_time else "",
        "delivery_location": order.delivery_location,
        "status": order.status,
        "total_amount": str(order.total_amount),
    }


def _save_order_items(*, formset, order: Order) -> tuple[list[str], list[str]]:
    formset.instance = order
    items = formset.save(commit=False)
    deleted_ids = [str(item.pk) for item in getattr(formset, "deleted_objects", ())]
    for item in getattr(formset, "deleted_objects", ()):
        item.delete()

    saved_ids: list[str] = []
    for item in items:
        item.order = order
        item.full_clean()
        item.save()
        saved_ids.append(str(item.pk))
    formset.save_m2m()
    order.recalculate_total()
    return saved_ids, deleted_ids


def create_order_from_forms(
    *, order_form, item_formset, actor, creation_key: str
) -> tuple[Order, bool]:
    existing = Order.objects.filter(creation_key=creation_key).first()
    if existing:
        return existing, False

    try:
        with transaction.atomic():
            order = order_form.save(commit=False)
            order.creation_key = creation_key
            order.status = Order.Status.PENDING
            order.created_by = actor
            order.updated_by = actor
            order.full_clean()
            order.save()
            saved_ids, _ = _save_order_items(formset=item_formset, order=order)
            order.refresh_from_db()
            record_audit(
                actor=actor,
                action="order.created",
                entity=order,
                payload={
                    **_order_snapshot(order),
                    "item_ids": saved_ids,
                    "item_count": order.items.count(),
                },
            )
            return order, True
    except IntegrityError:
        existing = Order.objects.filter(creation_key=creation_key).first()
        if existing:
            return existing, False
        raise


@transaction.atomic
def update_order_from_forms(*, order: Order, order_form, item_formset, actor) -> Order:
    locked = Order.objects.select_for_update().get(pk=order.pk)
    if locked.status not in ORDER_EDITABLE_STATUSES:
        raise ValidationError("O pedido não pode mais ser editado neste status.")

    before = _order_snapshot(locked)
    for field in (
        "company",
        "order_date",
        "delivery_date",
        "delivery_time",
        "delivery_location",
        "notes",
    ):
        setattr(locked, field, order_form.cleaned_data[field])
    locked.updated_by = actor
    locked.full_clean()
    locked.save()

    saved_ids: list[str] = []
    deleted_ids: list[str] = []
    if item_formset is not None:
        if locked.status != Order.Status.PENDING:
            raise ValidationError(
                "Os itens só podem ser alterados enquanto o pedido está pendente."
            )
        saved_ids, deleted_ids = _save_order_items(formset=item_formset, order=locked)

    locked.refresh_from_db()
    record_audit(
        actor=actor,
        action="order.updated",
        entity=locked,
        payload={
            "before": before,
            "after": _order_snapshot(locked),
            "saved_item_ids": saved_ids,
            "deleted_item_ids": deleted_ids,
        },
    )
    return locked


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
    if new_status != Order.Status.CANCELLED:
        if not order.items.exists():
            raise ValidationError("Adicione ao menos um item antes de avançar o pedido.")
        if order.total_amount <= 0:
            raise ValidationError("O pedido precisa ter valor total maior que zero.")

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
