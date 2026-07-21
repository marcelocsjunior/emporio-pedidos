from __future__ import annotations

import re
from calendar import monthrange
from datetime import date
from decimal import Decimal
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from accounts.access import Capability, user_has_capability

from .models import MonthlyClosing, Order
from .services import generate_monthly_closing, record_audit

CLOSING_TRANSITIONS: dict[str, set[str]] = {
    MonthlyClosing.Status.PENDING: {MonthlyClosing.Status.TO_REVIEW},
    MonthlyClosing.Status.TO_REVIEW: {
        MonthlyClosing.Status.PENDING,
        MonthlyClosing.Status.VALIDATED,
    },
    MonthlyClosing.Status.VALIDATED: {MonthlyClosing.Status.INVOICED},
    MonthlyClosing.Status.INVOICED: set(),
}


def format_brl(value: Decimal) -> str:
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def build_operational_closing_message(closing: MonthlyClosing) -> str:
    month = closing.reference_month.strftime("%m/%Y")
    return (
        f"Olá, {closing.company.name}.\n\n"
        f"Segue o fechamento do Empório Restaurante referente a {month}:\n"
        f"• Pedidos entregues: {closing.order_count}\n"
        f"• Total de itens: {closing.item_count}\n"
        f"• Valor total: {format_brl(closing.total_amount)}\n\n"
        "Peço, por gentileza, a conferência. Qualquer divergência, nos avise."
    )


def closing_orders_queryset(closing: MonthlyClosing) -> QuerySet[Order]:
    last_day = monthrange(closing.reference_month.year, closing.reference_month.month)[1]
    end = closing.reference_month.replace(day=last_day)
    return (
        Order.objects.filter(
            company=closing.company,
            delivery_date__range=(closing.reference_month, end),
            status=Order.Status.DELIVERED,
        )
        .select_related("company")
        .prefetch_related("items")
        .order_by("delivery_date", "delivery_time", "number")
    )


@transaction.atomic
def generate_or_recalculate_closing(
    *,
    company_id,
    reference_month: date,
    actor=None,
) -> MonthlyClosing:
    normalized_month = reference_month.replace(day=1)
    existed = MonthlyClosing.objects.filter(
        company_id=company_id,
        reference_month=normalized_month,
    ).exists()
    closing = generate_monthly_closing(
        company_id=company_id,
        reference_month=normalized_month,
        actor=actor,
    )
    message = build_operational_closing_message(closing)
    if closing.message_snapshot != message:
        closing.message_snapshot = message
        closing.save(update_fields=("message_snapshot", "updated_at"))
    if existed:
        record_audit(
            actor=actor,
            action="closing.recalculated",
            entity=closing,
            payload={
                "reference_month": normalized_month.isoformat(),
                "order_count": closing.order_count,
                "item_count": closing.item_count,
                "total_amount": str(closing.total_amount),
            },
        )
    return closing


def allowed_closing_statuses_for_user(user, closing: MonthlyClosing) -> list[str]:
    if not user_has_capability(user, Capability.REVIEW_CLOSINGS):
        return []
    return [
        value
        for value, _label in MonthlyClosing.Status.choices
        if value in CLOSING_TRANSITIONS[closing.status]
    ]


@transaction.atomic
def change_closing_status(
    *,
    closing_id,
    new_status: str,
    actor=None,
    reason: str = "",
) -> MonthlyClosing:
    closing = (
        MonthlyClosing.objects.select_for_update().select_related("company").get(pk=closing_id)
    )
    current_status = closing.status
    if new_status not in MonthlyClosing.Status.values:
        raise ValidationError("Status de fechamento inválido.")
    if new_status not in CLOSING_TRANSITIONS[current_status]:
        raise ValidationError(
            f"Transição de fechamento não permitida: {current_status} → {new_status}."
        )
    if new_status == MonthlyClosing.Status.VALIDATED:
        if closing.order_count < 1 or closing.total_amount <= 0:
            raise ValidationError(
                "O fechamento precisa ter pedidos entregues e valor positivo antes da validação."
            )

    now = timezone.now()
    closing.status = new_status
    update_fields = ["status", "updated_at"]
    if new_status == MonthlyClosing.Status.VALIDATED:
        closing.validated_at = now
        update_fields.append("validated_at")
    if new_status == MonthlyClosing.Status.INVOICED:
        if not closing.validated_at:
            raise ValidationError("Somente um fechamento validado pode ser faturado.")
        closing.invoiced_at = now
        update_fields.append("invoiced_at")
    closing.save(update_fields=tuple(update_fields))
    record_audit(
        actor=actor,
        action="closing.status_changed",
        entity=closing,
        payload={"from": current_status, "to": new_status, "reason": reason[:255]},
    )
    return closing


@transaction.atomic
def update_closing_notes(*, closing: MonthlyClosing, notes: str, actor=None) -> MonthlyClosing:
    locked = MonthlyClosing.objects.select_for_update().get(pk=closing.pk)
    previous = locked.notes
    locked.notes = notes.strip()
    locked.save(update_fields=("notes", "updated_at"))
    record_audit(
        actor=actor,
        action="closing.notes_updated",
        entity=locked,
        payload={"before": previous, "after": locked.notes},
    )
    return locked


def build_whatsapp_link(closing: MonthlyClosing) -> str:
    digits = re.sub(r"\D", "", closing.company.phone or "")
    if len(digits) in {10, 11}:
        digits = f"55{digits}"
    if len(digits) < 12:
        return ""
    return f"https://wa.me/{digits}?text={quote(closing.message_snapshot)}"
