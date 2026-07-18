from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from intelligence.models import AIEvent, AIRecommendation
from orders.models import AuditEvent


class Command(BaseCommand):
    help = "Expurga conteúdo operacional da IA conforme retenção, preservando evidência agregada."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Confirma o expurgo.")

    @transaction.atomic
    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=settings.AI_RETENTION_DAYS)
        recommendations = AIRecommendation.objects.filter(created_at__lt=cutoff)
        events = AIEvent.objects.filter(created_at__lt=cutoff)
        summary = {
            "cutoff": cutoff.isoformat(),
            "recommendations": recommendations.count(),
            "events": events.count(),
        }
        if not options["apply"]:
            self.stdout.write(f"DRY-RUN: {summary}")
            return
        AuditEvent.objects.create(
            actor=None,
            action="intelligence.retention_purge",
            entity_type="intelligence.retention",
            entity_id=cutoff.date().isoformat(),
            payload=summary,
        )
        recommendations.delete()
        events.delete()
        self.stdout.write(self.style.SUCCESS(f"Expurgo concluído: {summary}"))
