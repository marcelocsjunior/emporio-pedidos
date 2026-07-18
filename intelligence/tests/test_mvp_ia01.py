from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.roles import ROLE_ATTENDANCE, ROLE_FINANCE, ensure_roles
from intelligence.access import visible_recommendations_for_user
from intelligence.engine import (
    enqueue_due_events,
    process_available_events,
    recover_stale_events,
)
from intelligence.models import AIEvent, AIFeedback, AIRecommendation, DataContext
from intelligence.privacy import assert_payload_safe, sanitize_text
from orders.forms import CompanyForm
from orders.models import AuditEvent, Company, Order, OrderItem, Product

pytestmark = pytest.mark.django_db


def create_order(*, company: Company, delivery_time: time, status: str = Order.Status.RECEIVED):
    product = Product.objects.create(
        name=f"Produto {Product.objects.count() + 1}",
        category="Refeição",
        unit_price=Decimal("20.00"),
    )
    order = Order.objects.create(
        company=company,
        delivery_date=timezone.localdate(),
        delivery_time=delivery_time,
        delivery_location="Local interno",
        status=status,
    )
    OrderItem.objects.create(
        order=order,
        product=product,
        quantity=10,
        unit_price=product.unit_price,
    )
    order.refresh_from_db()
    return order


def create_recommendation(*, category: str) -> AIRecommendation:
    event = AIEvent.objects.create(
        event_type=AIEvent.EventType.DUPLICATE_ORDER,
        data_context=DataContext.REAL,
        source_type="test.source",
        source_id=category,
        payload={"candidate": {}},
        idempotency_key=f"event-{category}",
        status=AIEvent.Status.COMPLETED,
    )
    return AIRecommendation.objects.create(
        event=event,
        category=category,
        severity=AIRecommendation.Severity.ATTENTION,
        data_context=DataContext.REAL,
        source_type="test.source",
        source_id=category,
        title="Recomendação de teste",
        summary="Resumo de teste",
        evidence={"safe": True},
        confidence=Decimal("0.900"),
        idempotency_key=f"recommendation-{category}",
    )


def test_company_form_exposes_demo_flag():
    form = CompanyForm(
        data={
            "name": "Empresa demonstração",
            "responsible_name": "",
            "phone": "",
            "address": "",
            "city": "",
            "customer_type": Company.CustomerType.SPOT,
            "payment_terms": "",
            "is_demo": "on",
            "notes": "",
        }
    )
    assert form.is_valid(), form.errors
    company = form.save()
    assert company.is_demo is True
    audit = AuditEvent.objects.get(
        action="company.data_context_assigned",
        entity_id=str(company.pk),
    )
    assert audit.payload == {"from": None, "to": True}


def test_sanitizer_removes_sensitive_identifiers():
    result = sanitize_text(
        "Falar com Maria em maria@example.com ou (31) 99999-9999. CNPJ 12.345.678/0001-90.",
        redaction_terms=("Maria",),
    )
    assert "Maria" not in result
    assert "maria@example.com" not in result
    assert "99999-9999" not in result
    assert "12.345.678/0001-90" not in result
    assert_payload_safe({"notes": result}, forbidden_terms=("Maria",))


@override_settings(AI_ENABLED=False, AI_MODE="pilot")
def test_delay_processing_is_idempotent():
    company = Company.objects.create(name="Cliente real")
    fixed_now = timezone.make_aware(
        datetime.combine(timezone.localdate(), time(9, 40)),
        timezone.get_current_timezone(),
    )
    order = create_order(company=company, delivery_time=time(10, 0))

    first = enqueue_due_events(now=fixed_now)
    process_available_events(limit=20)
    second = enqueue_due_events(now=fixed_now)
    process_available_events(limit=20)

    assert first[AIEvent.EventType.DELAY_RISK] == 1
    assert second[AIEvent.EventType.DELAY_RISK] == 0
    assert AIRecommendation.objects.filter(
        category=AIRecommendation.Category.DELAY,
        source_id=str(order.pk),
    ).count() == 1


@override_settings(AI_ENABLED=False, AI_MODE="pilot")
def test_production_summaries_do_not_mix_demo_and_real():
    real = Company.objects.create(name="Cliente real", is_demo=False)
    demo = Company.objects.create(name="Cliente demo", is_demo=True)
    create_order(company=real, delivery_time=time(12, 0))
    create_order(company=demo, delivery_time=time(12, 10))

    enqueue_due_events()
    process_available_events(limit=20)

    contexts = set(
        AIRecommendation.objects.filter(
            category=AIRecommendation.Category.PRODUCTION
        ).values_list("data_context", flat=True)
    )
    assert contexts == {DataContext.REAL, DataContext.DEMO}


@override_settings(AI_MODE="pilot")
def test_profile_permissions_limit_categories():
    groups = ensure_roles(strict=True)
    user_model = get_user_model()
    attendance = user_model.objects.create_user(username="atendimento", password="senha-forte-123")
    finance = user_model.objects.create_user(username="financeiro", password="senha-forte-123")
    attendance.groups.add(groups[ROLE_ATTENDANCE])
    finance.groups.add(groups[ROLE_FINANCE])

    duplicate = create_recommendation(category=AIRecommendation.Category.DUPLICATE)
    closing = create_recommendation(category=AIRecommendation.Category.CLOSING)

    assert list(visible_recommendations_for_user(attendance)) == [duplicate]
    assert list(visible_recommendations_for_user(finance)) == [closing]


@override_settings(AI_MODE="pilot")
def test_feedback_is_recorded_and_audited(client):
    groups = ensure_roles(strict=True)
    user = get_user_model().objects.create_user(
        username="operador",
        password="senha-forte-123",
    )
    user.groups.add(groups[ROLE_ATTENDANCE])
    recommendation = create_recommendation(category=AIRecommendation.Category.DUPLICATE)
    client.force_login(user)

    response = client.post(
        reverse("intelligence:feedback", kwargs={"pk": recommendation.pk}),
        {"rating": AIFeedback.Rating.USEFUL, "notes": "Alerta confirmado."},
    )

    assert response.status_code == 302
    feedback = AIFeedback.objects.get(recommendation=recommendation, user=user)
    assert feedback.rating == AIFeedback.Rating.USEFUL
    recommendation.refresh_from_db()
    assert recommendation.status == AIRecommendation.Status.USEFUL
    assert AuditEvent.objects.filter(
        action="intelligence.feedback_created",
        actor=user,
    ).exists()


@override_settings(AI_ENABLED=True, AI_MODE="pilot", AI_MAX_ATTEMPTS=5)
def test_transient_provider_failure_stops_after_five_attempts(monkeypatch):
    company = Company.objects.create(name="Cliente com falha temporária")
    fixed_now = timezone.make_aware(
        datetime.combine(timezone.localdate(), time(9, 40)),
        timezone.get_current_timezone(),
    )
    create_order(company=company, delivery_time=time(10, 0))
    enqueue_due_events(now=fixed_now)
    event = AIEvent.objects.filter(event_type=AIEvent.EventType.DELAY_RISK).get()

    from intelligence.providers import ProviderTransientError

    def fail_generate(*args, **kwargs):
        raise ProviderTransientError("http_429")

    monkeypatch.setattr("intelligence.processor.GeminiProvider.generate", fail_generate)

    from intelligence.engine import process_next_event

    AIEvent.objects.exclude(pk=event.pk).update(status=AIEvent.Status.COMPLETED)

    for attempt in range(5):
        if attempt:
            event.next_attempt_at = timezone.now()
            event.save(update_fields=("next_attempt_at", "updated_at"))
        process_next_event()
        event.refresh_from_db()

    assert event.status == AIEvent.Status.FAILED
    assert event.attempts == 5
    assert event.last_error_code == "http_429"
    assert AIRecommendation.objects.filter(
        category=AIRecommendation.Category.SYSTEM,
        source_id=str(event.pk),
    ).count() == 1


@override_settings(AI_ENABLED=False, AI_MODE="pilot")
def test_delay_escalation_supersedes_previous_recommendation():
    company = Company.objects.create(name="Cliente com escalonamento")
    order = create_order(company=company, delivery_time=time(10, 30))
    attention_now = timezone.make_aware(
        datetime.combine(timezone.localdate(), time(9, 40)),
        timezone.get_current_timezone(),
    )
    critical_now = timezone.make_aware(
        datetime.combine(timezone.localdate(), time(10, 5)),
        timezone.get_current_timezone(),
    )

    enqueue_due_events(now=attention_now)
    process_available_events(limit=20)
    first = AIRecommendation.objects.get(
        category=AIRecommendation.Category.DELAY,
        source_id=str(order.pk),
    )
    assert first.severity == AIRecommendation.Severity.ATTENTION

    enqueue_due_events(now=critical_now)
    process_available_events(limit=20)
    first.refresh_from_db()
    current = AIRecommendation.objects.filter(
        category=AIRecommendation.Category.DELAY,
        source_id=str(order.pk),
    ).exclude(pk=first.pk).get()

    assert first.status == AIRecommendation.Status.EXPIRED
    assert current.severity == AIRecommendation.Severity.CRITICAL


@override_settings(AI_MODE="pilot")
def test_stale_processing_event_is_recovered():
    event = AIEvent.objects.create(
        event_type=AIEvent.EventType.PRODUCTION_SUMMARY,
        data_context=DataContext.REAL,
        source_type="test.stale",
        source_id="stale-1",
        payload={"candidate": {}},
        idempotency_key="stale-event",
        status=AIEvent.Status.PROCESSING,
        locked_at=timezone.now() - timedelta(minutes=30),
    )

    recovered = recover_stale_events(older_than_minutes=10)
    event.refresh_from_db()

    assert recovered == 1
    assert event.status == AIEvent.Status.PENDING
    assert event.locked_at is None
    assert event.last_error_code == "stale_lock_recovered"


@override_settings(AI_ENABLED=False, AI_MODE="pilot")
def test_company_context_change_creates_new_idempotent_event():
    company = Company.objects.create(name="Cliente alternável", is_demo=False)
    fixed_now = timezone.make_aware(
        datetime.combine(timezone.localdate(), time(9, 40)),
        timezone.get_current_timezone(),
    )
    order = create_order(company=company, delivery_time=time(10, 0))

    enqueue_due_events(now=fixed_now)
    process_available_events(limit=20)
    company.is_demo = True
    company.save(update_fields=("is_demo", "updated_at"))
    enqueue_due_events(now=fixed_now)
    process_available_events(limit=20)

    contexts = set(
        AIRecommendation.objects.filter(
            category=AIRecommendation.Category.DELAY,
            source_id=str(order.pk),
        ).values_list("data_context", flat=True)
    )
    assert contexts == {DataContext.REAL, DataContext.DEMO}
    assert AIRecommendation.objects.filter(
        category=AIRecommendation.Category.DELAY,
        source_id=str(order.pk),
        status=AIRecommendation.Status.EXPIRED,
    ).count() == 1


@override_settings(AI_MODE="pilot")
def test_administrator_can_requeue_failed_event(client):
    user = get_user_model().objects.create_superuser(
        username="admin-retry",
        password="senha-forte-123",
    )
    event = AIEvent.objects.create(
        event_type=AIEvent.EventType.DELAY_RISK,
        data_context=DataContext.REAL,
        source_type="orders.order",
        source_id="retry-source",
        payload={"candidate": {}},
        idempotency_key="retry-event",
        status=AIEvent.Status.FAILED,
        attempts=5,
        last_error_code="http_429",
    )
    recommendation = AIRecommendation.objects.create(
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
        idempotency_key="retry-system-alert",
    )
    client.force_login(user)

    response = client.post(
        reverse("intelligence:retry", kwargs={"pk": recommendation.pk}),
    )

    assert response.status_code == 302
    event.refresh_from_db()
    recommendation.refresh_from_db()
    assert event.status == AIEvent.Status.PENDING
    assert event.attempts == 0
    assert event.last_error_code == ""
    assert recommendation.status == AIRecommendation.Status.EXPIRED
    assert AuditEvent.objects.filter(
        action="intelligence.failed_event_requeued",
        actor=user,
    ).exists()
