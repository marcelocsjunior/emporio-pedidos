import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from orders.models import Company, Order, OrderItem, Product

from intelligence.active_assistant import (
    CATEGORY_NEW_ORDER,
    EVENT_TYPE_ORDER_CREATED,
    ActiveOrderGeminiProvider,
    notify_order_created,
    process_active_order_events,
)
from intelligence.models import AIEvent, AIRecommendation
from intelligence.providers import ProviderPermanentError


@override_settings(
    AI_ACTIVE_ASSISTANT_ENABLED=True,
    AI_ACTIVE_ASSISTANT_PROMPT_VERSION="mvp-ia-03-test",
)
class ActiveAssistantCoreTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Empresa Sigilosa",
            responsible_name="Pessoa Responsável",
            phone="(31) 99999-9999",
            address="Rua Protegida, 10",
            city="Itabirito",
            active=True,
        )
        self.product = Product.objects.create(
            name="Marmita executiva",
            unit_price=Decimal("25.00"),
        )
        self.order = Order.objects.create(
            company=self.company,
            delivery_date=timezone.localdate(),
            delivery_time=(timezone.localtime() + timedelta(hours=3)).time(),
            delivery_location="Rua Protegida, 10",
            notes="Entregar para Pessoa Responsável no telefone (31) 99999-9999",
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=3,
            unit_price=self.product.unit_price,
        )
        self.order.refresh_from_db()

    def test_notification_is_immediate_idempotent_and_sanitized(self):
        created = notify_order_created(self.order)
        repeated = notify_order_created(self.order)

        self.assertTrue(created)
        self.assertFalse(repeated)
        self.assertEqual(AIEvent.objects.count(), 1)
        self.assertEqual(AIRecommendation.objects.count(), 1)

        event = AIEvent.objects.get()
        recommendation = AIRecommendation.objects.get()
        serialized = json.dumps(event.payload, ensure_ascii=False)

        self.assertEqual(event.event_type, EVENT_TYPE_ORDER_CREATED)
        self.assertEqual(recommendation.category, CATEGORY_NEW_ORDER)
        self.assertEqual(recommendation.status, AIRecommendation.Status.NEW)
        self.assertNotIn(self.company.name, serialized)
        self.assertNotIn(self.company.phone, serialized)
        self.assertNotIn(self.company.address, serialized)
        self.assertNotIn(self.order.delivery_location, serialized)
        self.assertIn("[DADO_REMOVIDO]", serialized)

    @override_settings(AI_ENABLED=False)
    def test_worker_enriches_same_notification_without_duplication(self):
        notify_order_created(self.order)
        recommendation_id = AIRecommendation.objects.get().pk

        processed = process_active_order_events(limit=10)

        self.assertEqual(processed, 1)
        self.assertEqual(AIRecommendation.objects.count(), 1)
        recommendation = AIRecommendation.objects.get(pk=recommendation_id)
        self.assertEqual(recommendation.evidence["analysis_status"], "completed")
        self.assertTrue(recommendation.action_suggested)
        self.assertEqual(recommendation.status, AIRecommendation.Status.NEW)
        self.assertEqual(AIEvent.objects.get().status, AIEvent.Status.COMPLETED)

    @override_settings(AI_ENABLED=False)
    def test_viewed_state_is_preserved_when_analysis_finishes(self):
        notify_order_created(self.order)
        recommendation = AIRecommendation.objects.get()
        recommendation.status = AIRecommendation.Status.VIEWED
        recommendation.save(update_fields=("status", "updated_at"))

        process_active_order_events(limit=10)

        recommendation.refresh_from_db()
        self.assertEqual(recommendation.status, AIRecommendation.Status.VIEWED)
        self.assertEqual(recommendation.evidence["analysis_status"], "completed")

    @override_settings(AI_ENABLED=True, AI_MAX_ATTEMPTS=1)
    def test_provider_failure_preserves_operator_notification(self):
        notify_order_created(self.order)

        with patch.object(
            ActiveOrderGeminiProvider,
            "generate",
            side_effect=ProviderPermanentError("provider_unavailable"),
        ):
            processed = process_active_order_events(limit=10)

        self.assertEqual(processed, 1)
        recommendation = AIRecommendation.objects.get()
        event = AIEvent.objects.get()
        self.assertEqual(recommendation.status, AIRecommendation.Status.NEW)
        self.assertEqual(recommendation.evidence["analysis_status"], "failed")
        self.assertIn("temporariamente indisponível", recommendation.summary)
        self.assertEqual(event.status, AIEvent.Status.FAILED)
