from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time
from types import MappingProxyType

from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils import timezone

from customer_portal.models import CustomerOrderRequest
from orders.models import Order
from orders.services import build_order_message

from .access import visible_recommendations_for_user
from .candidates import ACTIVE_ORDER_STATUSES, _delay_candidate
from .models import AIRecommendation

DISPLAY_LIMIT = 10
REQUEST_SCAN_LIMIT = 50
ORDER_SCAN_LIMIT = 50
AI_SCAN_LIMIT = 30

SEVERITY_RANK = {
    AIRecommendation.Severity.CRITICAL: 0,
    AIRecommendation.Severity.ATTENTION: 1,
    AIRecommendation.Severity.INFO: 2,
}

KIND_AUTHORIZATION = "authorization"
KIND_INCONSISTENCY = "inconsistency"
KIND_PROGRESS = "progress"
KIND_DELIVERY = "delivery"
KIND_INTELLIGENCE = "intelligence"


@dataclass(frozen=True, slots=True)
class AssistantCard:
    kind: str
    severity: str
    title: str
    summary: str
    reference: str
    company_name: str
    delivery_label: str
    action_label: str
    action_url: str
    suggested_action: str
    message_suggestion: str
    sort_at: datetime
    source_key: str

    @property
    def severity_label(self) -> str:
        try:
            return AIRecommendation.Severity(self.severity).label
        except ValueError:
            return self.severity


@dataclass(frozen=True, slots=True)
class OperationalAssistantPanel:
    cards: tuple[AssistantCard, ...]
    counts: Mapping[str, int]
    total_open: int
    displayed_count: int
    generated_at: datetime


def _aware_delivery_at(*, delivery_date, delivery_time, fallback_end_of_day: bool) -> datetime:
    resolved_time = delivery_time
    if resolved_time is None:
        resolved_time = time.max if fallback_end_of_day else time.min
    return timezone.make_aware(
        datetime.combine(delivery_date, resolved_time),
        timezone.get_current_timezone(),
    )


def _delivery_label(delivery_date, delivery_time) -> str:
    date_label = delivery_date.strftime("%d/%m/%Y")
    if delivery_time is None:
        return f"{date_label} · horário a combinar"
    return f"{date_label} · {delivery_time.strftime('%H:%M')}"


def _request_message(customer_request: CustomerOrderRequest) -> str:
    return (
        f"Olá, sua solicitação {customer_request.protocol} foi recebida e está em análise "
        "pela nossa equipe. Assim que for autorizada, o pedido oficial ficará disponível "
        "para acompanhamento no portal."
    )


def _request_cards(user, *, now: datetime) -> list[AssistantCard]:
    if not user.has_perm("customer_portal.review_customerorderrequest"):
        return []

    duplicate_statuses = (
        CustomerOrderRequest.Status.SUBMITTED,
        CustomerOrderRequest.Status.IN_REVIEW,
        CustomerOrderRequest.Status.APPROVED,
        CustomerOrderRequest.Status.CONVERTED,
    )
    other_requests = CustomerOrderRequest.objects.filter(
        company_id=OuterRef("company_id"),
        delivery_date=OuterRef("delivery_date"),
        total_amount=OuterRef("total_amount"),
        status__in=duplicate_statuses,
    ).exclude(pk=OuterRef("pk"))
    matching_orders = Order.objects.filter(
        company_id=OuterRef("company_id"),
        delivery_date=OuterRef("delivery_date"),
        total_amount=OuterRef("total_amount"),
    ).exclude(status=Order.Status.CANCELLED)

    requests = list(
        CustomerOrderRequest.objects.filter(
            status__in=(
                CustomerOrderRequest.Status.SUBMITTED,
                CustomerOrderRequest.Status.IN_REVIEW,
            )
        )
        .select_related("company", "delivery_location")
        .annotate(
            has_similar_request=Exists(other_requests),
            has_similar_order=Exists(matching_orders),
        )
        .order_by("delivery_date", "delivery_time", "submitted_at", "created_at")[
            :REQUEST_SCAN_LIMIT
        ]
    )

    cards: list[AssistantCard] = []
    for customer_request in requests:
        delivery_at = _aware_delivery_at(
            delivery_date=customer_request.delivery_date,
            delivery_time=customer_request.delivery_time,
            fallback_end_of_day=True,
        )
        minutes_to_delivery = int((delivery_at - now).total_seconds() // 60)
        duplicate = customer_request.has_similar_request or customer_request.has_similar_order

        if minutes_to_delivery <= 30:
            severity = AIRecommendation.Severity.CRITICAL
            title = f"{customer_request.protocol} requer autorização imediata"
            summary = (
                "A entrega está vencida ou ocorre em até 30 minutos e ainda não foi autorizada."
            )
            suggested_action = "Abrir a solicitação e decidir antes de qualquer produção."
            kind = KIND_AUTHORIZATION
        elif duplicate:
            severity = AIRecommendation.Severity.ATTENTION
            title = f"Conferir possível duplicidade em {customer_request.protocol}"
            summary = (
                "Existe outra solicitação ou pedido da mesma empresa com data e valor iguais."
            )
            suggested_action = "Comparar os registros antes de autorizar."
            kind = KIND_INCONSISTENCY
        else:
            severity = AIRecommendation.Severity.ATTENTION
            title = f"{customer_request.protocol} aguardando autorização"
            summary = "A solicitação do cliente está disponível para triagem da Central Comercial."
            suggested_action = "Conferir itens, entrega e observações antes de decidir."
            kind = KIND_AUTHORIZATION

        cards.append(
            AssistantCard(
                kind=kind,
                severity=severity,
                title=title,
                summary=summary,
                reference=customer_request.protocol,
                company_name=customer_request.company.name,
                delivery_label=_delivery_label(
                    customer_request.delivery_date,
                    customer_request.delivery_time,
                ),
                action_label="Abrir solicitação",
                action_url=reverse(
                    "customer_portal:request-review",
                    kwargs={"pk": customer_request.pk},
                ),
                suggested_action=suggested_action,
                message_suggestion=_request_message(customer_request),
                sort_at=delivery_at,
                source_key=f"customer_request:{customer_request.pk}",
            )
        )
    return cards


def _visible_ai_recommendations(user) -> list[AIRecommendation]:
    return list(
        visible_recommendations_for_user(user)
        .filter(
            status__in=(AIRecommendation.Status.NEW, AIRecommendation.Status.VIEWED),
            category__in=(
                AIRecommendation.Category.DELAY,
                AIRecommendation.Category.DUPLICATE,
                AIRecommendation.Category.SYSTEM,
            ),
        )
        .order_by("severity", "-created_at")[:AI_SCAN_LIMIT]
    )


def _order_cards(
    user,
    *,
    now: datetime,
    recommendations: list[AIRecommendation],
) -> list[AssistantCard]:
    if not user.has_perm("orders.view_order"):
        return []

    local_now = timezone.localtime(now)
    delay_recommendations = {
        recommendation.source_id: recommendation
        for recommendation in recommendations
        if recommendation.category == AIRecommendation.Category.DELAY
        and recommendation.source_type == "orders.order"
    }
    orders = list(
        Order.objects.filter(
            delivery_date=local_now.date(),
            status__in=ACTIVE_ORDER_STATUSES,
        )
        .select_related("company")
        .prefetch_related("items")
        .order_by("delivery_time", "created_at")[:ORDER_SCAN_LIMIT]
    )

    cards: list[AssistantCard] = []
    for order in orders:
        delivery_at = _aware_delivery_at(
            delivery_date=order.delivery_date,
            delivery_time=order.delivery_time,
            fallback_end_of_day=True,
        )
        candidate = _delay_candidate(order, now=local_now)
        recommendation = delay_recommendations.get(str(order.pk))

        if candidate is not None:
            severity = candidate["severity"]
            title = recommendation.title if recommendation else candidate["title"]
            summary = recommendation.summary if recommendation else candidate["summary"]
            suggested_action = (
                recommendation.action_suggested
                if recommendation and recommendation.action_suggested
                else candidate["action_suggested"]
            )
            kind = KIND_DELIVERY
        elif order.status in (Order.Status.PENDING, Order.Status.RECEIVED):
            severity = AIRecommendation.Severity.ATTENTION
            title = f"Pedido {order.number} aguardando andamento"
            summary = (
                "O pedido está autorizado, mas ainda precisa avançar no fluxo operacional."
            )
            suggested_action = "Abrir o pedido e conferir a próxima transição permitida."
            kind = KIND_PROGRESS
        else:
            continue

        cards.append(
            AssistantCard(
                kind=kind,
                severity=severity,
                title=title,
                summary=summary,
                reference=order.number,
                company_name=order.company.name,
                delivery_label=_delivery_label(order.delivery_date, order.delivery_time),
                action_label="Abrir pedido",
                action_url=reverse("order-detail", kwargs={"pk": order.pk}),
                suggested_action=suggested_action,
                message_suggestion=build_order_message(order),
                sort_at=delivery_at,
                source_key=f"order:{order.pk}",
            )
        )
    return cards


def _standalone_ai_cards(
    user,
    *,
    now: datetime,
    recommendations: list[AIRecommendation],
) -> list[AssistantCard]:
    cards: list[AssistantCard] = []
    can_view_orders = user.has_perm("orders.view_order")

    for recommendation in recommendations:
        if recommendation.category == AIRecommendation.Category.DUPLICATE:
            if not can_view_orders:
                continue
            cards.append(
                AssistantCard(
                    kind=KIND_INCONSISTENCY,
                    severity=recommendation.severity,
                    title=recommendation.title,
                    summary=recommendation.summary,
                    reference="Recomendação da IA",
                    company_name="Conferência operacional",
                    delivery_label="Pedidos de hoje ou amanhã",
                    action_label="Ver pedidos",
                    action_url=reverse("order-list"),
                    suggested_action=recommendation.action_suggested,
                    message_suggestion="",
                    sort_at=recommendation.created_at,
                    source_key=f"ai_recommendation:{recommendation.pk}",
                )
            )
        elif recommendation.category == AIRecommendation.Category.SYSTEM:
            cards.append(
                AssistantCard(
                    kind=KIND_INTELLIGENCE,
                    severity=recommendation.severity,
                    title=recommendation.title,
                    summary=recommendation.summary,
                    reference="Central Inteligente",
                    company_name="Supervisão técnica",
                    delivery_label="Processamento da IA",
                    action_label="Abrir Central Inteligente",
                    action_url=reverse("intelligence:central"),
                    suggested_action=recommendation.action_suggested,
                    message_suggestion="",
                    sort_at=recommendation.created_at or now,
                    source_key=f"ai_recommendation:{recommendation.pk}",
                )
            )
    return cards


def _sort_key(card: AssistantCard) -> tuple[int, datetime, str]:
    return (SEVERITY_RANK.get(card.severity, 99), card.sort_at, card.source_key)


def build_operational_assistant(
    user,
    *,
    now: datetime | None = None,
    limit: int = DISPLAY_LIMIT,
) -> OperationalAssistantPanel:
    current = timezone.localtime(now or timezone.now())
    safe_limit = max(1, min(limit, DISPLAY_LIMIT))
    recommendations = _visible_ai_recommendations(user)

    cards = [
        *_request_cards(user, now=current),
        *_order_cards(user, now=current, recommendations=recommendations),
        *_standalone_ai_cards(user, now=current, recommendations=recommendations),
    ]

    unique_cards: dict[str, AssistantCard] = {}
    for card in sorted(cards, key=_sort_key):
        unique_cards.setdefault(card.source_key, card)
    ordered = list(unique_cards.values())

    counts = {
        KIND_AUTHORIZATION: 0,
        KIND_INCONSISTENCY: 0,
        KIND_PROGRESS: 0,
        KIND_DELIVERY: 0,
        KIND_INTELLIGENCE: 0,
    }
    for card in ordered:
        counts[card.kind] = counts.get(card.kind, 0) + 1

    displayed = tuple(ordered[:safe_limit])
    return OperationalAssistantPanel(
        cards=displayed,
        counts=MappingProxyType(counts),
        total_open=len(ordered),
        displayed_count=len(displayed),
        generated_at=current,
    )
