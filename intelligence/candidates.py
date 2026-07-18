from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import combinations

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from orders.models import MonthlyClosing, Order

from .models import AIEvent, AIPromptVersion, AIRecommendation, DataContext
from .privacy import assert_payload_safe, sanitize_text
from .providers import RESPONSE_SCHEMA, SYSTEM_PROMPT

ACTIVE_ORDER_STATUSES = (
    Order.Status.PENDING,
    Order.Status.RECEIVED,
    Order.Status.IN_PRODUCTION,
    Order.Status.OUT_FOR_DELIVERY,
)


def _hash_payload(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _company_ref(company_id) -> str:
    return f"COMP-{hashlib.sha256(str(company_id).encode()).hexdigest()[:12].upper()}"


def _context(is_demo: bool) -> str:
    return DataContext.DEMO if is_demo else DataContext.REAL


def _prompt_version() -> AIPromptVersion:
    prompt, _ = AIPromptVersion.objects.get_or_create(
        key="operational-supervisor",
        version=settings.AI_PROMPT_VERSION,
        defaults={
            "system_prompt": SYSTEM_PROMPT,
            "response_schema": RESPONSE_SCHEMA,
            "active": True,
        },
    )
    return prompt


def _enqueue_candidate(
    *,
    event_type: str,
    data_context: str,
    source_type: str,
    source_id: str,
    source_version: str,
    candidate: dict,
) -> tuple[AIEvent, bool]:
    prompt = _prompt_version()
    key_material = {
        "event_type": event_type,
        "data_context": data_context,
        "source_type": source_type,
        "source_id": source_id,
        "source_version": source_version,
        "prompt": prompt.version,
        "model": settings.GEMINI_MODEL,
    }
    idempotency_key = _hash_payload(key_material)
    payload = {
        "candidate": candidate,
        "source_version": source_version,
        "prompt_version": prompt.version,
    }
    assert_payload_safe(payload)
    event, created = AIEvent.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "event_type": event_type,
            "data_context": data_context,
            "source_type": source_type,
            "source_id": source_id,
            "payload": payload,
        },
    )
    if created:
        AIEvent.objects.filter(
            event_type=event_type,
            source_type=source_type,
            source_id=source_id,
            status=AIEvent.Status.PENDING,
        ).exclude(pk=event.pk).update(
            status=AIEvent.Status.SUPERSEDED,
            locked_at=None,
            updated_at=timezone.now(),
        )
    return event, created


def _order_redaction_terms(order: Order) -> tuple[str, ...]:
    company = order.company
    return tuple(
        value
        for value in (
            company.name,
            company.responsible_name,
            company.phone,
            company.address,
            company.city,
        )
        if value
    )


def _delay_candidate(order: Order, *, now: datetime) -> dict | None:
    if not order.delivery_time or order.status not in ACTIVE_ORDER_STATUSES:
        return None
    delivery_at = timezone.make_aware(
        datetime.combine(order.delivery_date, order.delivery_time),
        timezone.get_current_timezone(),
    )
    minutes = int((delivery_at - now).total_seconds() // 60)
    severity = None
    title = ""
    summary = ""

    if minutes < 0:
        risk_stage = "overdue"
        severity = AIRecommendation.Severity.CRITICAL
        title = f"Pedido {order.number} com horário vencido"
        summary = "O horário de entrega venceu e o pedido ainda não está marcado como entregue."
    elif minutes <= 30 and order.status not in (
        Order.Status.OUT_FOR_DELIVERY,
        Order.Status.DELIVERED,
    ):
        risk_stage = "critical"
        severity = AIRecommendation.Severity.CRITICAL
        title = f"Pedido {order.number} em risco crítico de atraso"
        summary = "Faltam 30 minutos ou menos e o pedido ainda não saiu para entrega."
    elif minutes <= 60 and order.status in (Order.Status.PENDING, Order.Status.RECEIVED):
        risk_stage = "attention"
        severity = AIRecommendation.Severity.ATTENTION
        title = f"Pedido {order.number} requer atenção"
        summary = "Faltam 60 minutos ou menos e o pedido ainda não entrou em produção."
    else:
        return None

    item_count = order.items.aggregate(total=Sum("quantity"))["total"] or 0
    notes = sanitize_text(order.notes, redaction_terms=_order_redaction_terms(order))
    return {
        "category": AIRecommendation.Category.DELAY,
        "severity": severity,
        "title": title,
        "summary": summary,
        "action_suggested": (
            "Priorizar a conferência operacional; nenhuma mudança de status é automática."
        ),
        "confidence": 1.0,
        "evidence": {
            "order_ref": order.number,
            "company_ref": _company_ref(order.company_id),
            "status": order.status,
            "delivery_at": delivery_at.isoformat(),
            "minutes_to_delivery": minutes,
            "risk_stage": risk_stage,
            "item_quantity": item_count,
            "notes_sanitized": notes,
        },
    }


def _item_signature(order: Order) -> dict[str, int]:
    return {str(item.product_id): item.quantity for item in order.items.all()}


def _duplicate_score(first: Order, second: Order) -> float:
    first_items = _item_signature(first)
    second_items = _item_signature(second)
    all_products = set(first_items) | set(second_items)
    if not all_products:
        return 0.0
    overlap = sum(min(first_items.get(key, 0), second_items.get(key, 0)) for key in all_products)
    maximum = sum(max(first_items.get(key, 0), second_items.get(key, 0)) for key in all_products)
    item_score = overlap / maximum if maximum else 0

    amount_base = max(first.total_amount, second.total_amount, Decimal("0.01"))
    amount_difference = abs(first.total_amount - second.total_amount) / amount_base
    amount_score = 1.0 if amount_difference <= Decimal("0.01") else 0.0

    time_score = 0.0
    if first.delivery_time and second.delivery_time:
        first_minutes = first.delivery_time.hour * 60 + first.delivery_time.minute
        second_minutes = second.delivery_time.hour * 60 + second.delivery_time.minute
        difference = abs(first_minutes - second_minutes)
        if difference <= 15:
            time_score = 1.0
        elif difference <= 60:
            time_score = 0.5

    location_score = 1.0 if first.delivery_location == second.delivery_location else 0.0
    score = 0.55 * item_score + 0.2 * amount_score + 0.15 * time_score
    score += 0.1 * location_score
    return round(score, 3)


def _duplicate_candidate(first: Order, second: Order) -> dict | None:
    score = _duplicate_score(first, second)
    if score < 0.75:
        return None
    severity = (
        AIRecommendation.Severity.CRITICAL
        if score >= 0.9
        else AIRecommendation.Severity.ATTENTION
    )
    return {
        "category": AIRecommendation.Category.DUPLICATE,
        "severity": severity,
        "title": f"Conferir possível duplicidade: {first.number} e {second.number}",
        "summary": "Dois pedidos da mesma empresa têm itens, valores e horários semelhantes.",
        "action_suggested": (
            "Conferir os pedidos antes de qualquer alteração; nenhum registro foi bloqueado."
        ),
        "confidence": score,
        "evidence": {
            "company_ref": _company_ref(first.company_id),
            "order_refs": [first.number, second.number],
            "delivery_date": first.delivery_date.isoformat(),
            "delivery_times": [
                first.delivery_time.isoformat() if first.delivery_time else None,
                second.delivery_time.isoformat() if second.delivery_time else None,
            ],
            "totals": [str(first.total_amount), str(second.total_amount)],
            "similarity": score,
        },
    }


def _production_candidate(*, target_date: date, is_demo: bool, orders: list[Order]) -> dict:
    products: dict[str, int] = {}
    time_windows: dict[str, int] = {}
    notes: list[str] = []
    total_quantity = 0
    for order in orders:
        for item in order.items.all():
            products[item.product_name] = products.get(item.product_name, 0) + item.quantity
            total_quantity += item.quantity
        window = order.delivery_time.strftime("%H:%M") if order.delivery_time else "Sem horário"
        time_windows[window] = time_windows.get(window, 0) + 1
        if order.notes:
            sanitized = sanitize_text(order.notes, redaction_terms=_order_redaction_terms(order))
            if sanitized:
                notes.append(sanitized)

    context_label = "demonstração" if is_demo else "dados reais"
    return {
        "category": AIRecommendation.Category.PRODUCTION,
        "severity": AIRecommendation.Severity.INFO,
        "title": f"Resumo de produção — {target_date:%d/%m/%Y} — {context_label}",
        "summary": (
            f"{len(orders)} pedidos totalizam {total_quantity} itens. "
            "Os dados reais e demonstrativos permanecem separados."
        ),
        "action_suggested": "Conferir volumes, horários e observações antes de iniciar a produção.",
        "confidence": 1.0,
        "evidence": {
            "date": target_date.isoformat(),
            "orders": len(orders),
            "item_quantity": total_quantity,
            "products": dict(sorted(products.items())),
            "delivery_windows": dict(sorted(time_windows.items())),
            "notes_sanitized": notes[:20],
        },
    }


def _closing_candidate(closing: MonthlyClosing) -> dict:
    last_day = monthrange(closing.reference_month.year, closing.reference_month.month)[1]
    end = closing.reference_month.replace(day=last_day)
    delivered = list(
        Order.objects.filter(
            company=closing.company,
            delivery_date__range=(closing.reference_month, end),
            status=Order.Status.DELIVERED,
        ).order_by("-total_amount")
    )
    actual_count = len(delivered)
    actual_total = sum((order.total_amount for order in delivered), Decimal("0.00"))
    previous = list(
        MonthlyClosing.objects.filter(
            company=closing.company,
            reference_month__lt=closing.reference_month,
            status__in=(MonthlyClosing.Status.VALIDATED, MonthlyClosing.Status.INVOICED),
        )
        .order_by("-reference_month")
        .values_list("total_amount", flat=True)[:3]
    )
    anomalies: list[str] = []
    severity = AIRecommendation.Severity.INFO

    if actual_count != closing.order_count or actual_total != closing.total_amount:
        anomalies.append("Totais do fechamento divergem dos pedidos entregues atuais.")
        severity = AIRecommendation.Severity.CRITICAL

    average = Decimal("0.00")
    variation = None
    if previous:
        average = sum(previous, Decimal("0.00")) / len(previous)
        if average > 0:
            variation = (closing.total_amount - average) / average
            if abs(variation) >= Decimal("0.25"):
                anomalies.append("Valor varia 25% ou mais em relação à média histórica disponível.")
                if severity != AIRecommendation.Severity.CRITICAL:
                    severity = AIRecommendation.Severity.ATTENTION
    else:
        anomalies.append("Sem base histórica suficiente para comparação de tendência.")

    largest_share = Decimal("0.00")
    if delivered and closing.total_amount > 0:
        largest_share = delivered[0].total_amount / closing.total_amount
        if largest_share > Decimal("0.30"):
            anomalies.append("Um único pedido representa mais de 30% do fechamento.")
            if severity != AIRecommendation.Severity.CRITICAL:
                severity = AIRecommendation.Severity.ATTENTION

    summary = (
        "Foram encontradas evidências que exigem conferência."
        if severity != AIRecommendation.Severity.INFO
        else "Auditoria determinística concluída sem bloqueios críticos."
    )
    return {
        "category": AIRecommendation.Category.CLOSING,
        "severity": severity,
        "title": f"Auditoria assistida do fechamento {closing.reference_month:%m/%Y}",
        "summary": summary,
        "action_suggested": "Conferir evidências antes de validar; a IA não valida nem fatura.",
        "confidence": 1.0,
        "evidence": {
            "company_ref": _company_ref(closing.company_id),
            "reference_month": closing.reference_month.isoformat(),
            "closing_order_count": closing.order_count,
            "actual_order_count": actual_count,
            "closing_total": str(closing.total_amount),
            "actual_total": str(actual_total),
            "previous_average": str(average),
            "variation": str(variation) if variation is not None else None,
            "largest_order_share": str(largest_share),
            "anomalies": anomalies,
        },
    }


def enqueue_due_events(*, now: datetime | None = None) -> dict[str, int]:
    now = now or timezone.now()
    local_now = timezone.localtime(now)
    today = local_now.date()
    tomorrow = today + timedelta(days=1)
    created = {event_type: 0 for event_type, _ in AIEvent.EventType.choices}

    active_orders = list(
        Order.objects.filter(delivery_date=today, status__in=ACTIVE_ORDER_STATUSES)
        .select_related("company")
        .prefetch_related("items")
    )
    for order in active_orders:
        candidate = _delay_candidate(order, now=local_now)
        if candidate:
            _, was_created = _enqueue_candidate(
                event_type=AIEvent.EventType.DELAY_RISK,
                data_context=_context(order.company.is_demo),
                source_type="orders.order",
                source_id=str(order.pk),
                source_version=_hash_payload(
                    {
                        "updated_at": order.updated_at.isoformat(),
                        "risk_stage": candidate["evidence"]["risk_stage"],
                    }
                ),
                candidate=candidate,
            )
            created[AIEvent.EventType.DELAY_RISK] += int(was_created)

    duplicate_orders = list(
        Order.objects.filter(
            delivery_date__in=(today, tomorrow),
        )
        .exclude(status=Order.Status.CANCELLED)
        .select_related("company")
        .prefetch_related("items")
        .order_by("company_id", "delivery_date", "created_at")
    )
    grouped: dict[tuple[object, date], list[Order]] = {}
    for order in duplicate_orders:
        grouped.setdefault((order.company_id, order.delivery_date), []).append(order)
    for orders in grouped.values():
        for first, second in combinations(orders, 2):
            candidate = _duplicate_candidate(first, second)
            if not candidate:
                continue
            source_ids = sorted((str(first.pk), str(second.pk)))
            source_version = _hash_payload(
                sorted((first.updated_at.isoformat(), second.updated_at.isoformat()))
            )
            _, was_created = _enqueue_candidate(
                event_type=AIEvent.EventType.DUPLICATE_ORDER,
                data_context=_context(first.company.is_demo),
                source_type="orders.order_pair",
                source_id=":".join(source_ids),
                source_version=source_version,
                candidate=candidate,
            )
            created[AIEvent.EventType.DUPLICATE_ORDER] += int(was_created)

    for target_date in (today, tomorrow):
        for is_demo in (False, True):
            orders = list(
                Order.objects.filter(
                    delivery_date=target_date,
                    company__is_demo=is_demo,
                )
                .exclude(status=Order.Status.CANCELLED)
                .select_related("company")
                .prefetch_related("items")
                .order_by("delivery_time", "number")
            )
            if not orders:
                continue
            candidate = _production_candidate(
                target_date=target_date,
                is_demo=is_demo,
                orders=orders,
            )
            source_version = _hash_payload(
                [(str(order.pk), order.updated_at.isoformat()) for order in orders]
            )
            _, was_created = _enqueue_candidate(
                event_type=AIEvent.EventType.PRODUCTION_SUMMARY,
                data_context=_context(is_demo),
                source_type="orders.production_day",
                source_id=f"{target_date.isoformat()}:{'demo' if is_demo else 'real'}",
                source_version=source_version,
                candidate=candidate,
            )
            created[AIEvent.EventType.PRODUCTION_SUMMARY] += int(was_created)

    closings = MonthlyClosing.objects.filter(
        status__in=(MonthlyClosing.Status.PENDING, MonthlyClosing.Status.TO_REVIEW)
    ).select_related("company")
    for closing in closings:
        candidate = _closing_candidate(closing)
        source_version = _hash_payload(
            {
                "updated_at": closing.updated_at.isoformat(),
                "order_count": closing.order_count,
                "total": str(closing.total_amount),
            }
        )
        _, was_created = _enqueue_candidate(
            event_type=AIEvent.EventType.CLOSING_AUDIT,
            data_context=_context(closing.company.is_demo),
            source_type="orders.monthlyclosing",
            source_id=str(closing.pk),
            source_version=source_version,
            candidate=candidate,
        )
        created[AIEvent.EventType.CLOSING_AUDIT] += int(was_created)

    return created


def _expiration_for(category: str) -> datetime:
    now = timezone.now()
    if category == AIRecommendation.Category.DELAY:
        return now + timedelta(hours=2)
    if category == AIRecommendation.Category.DUPLICATE:
        return now + timedelta(days=7)
    if category == AIRecommendation.Category.PRODUCTION:
        return now + timedelta(days=2)
    if category == AIRecommendation.Category.CLOSING:
        return now + timedelta(days=30)
    return now + timedelta(days=7)
