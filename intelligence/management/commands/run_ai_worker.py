from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from intelligence.active_assistant import process_active_order_events
from intelligence.engine import (
    enqueue_due_events,
    expire_stale_recommendations,
    process_available_events,
    recover_stale_events,
)


class Command(BaseCommand):
    help = "Executa o worker idempotente da Central Inteligente."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Executa um ciclo e encerra.")
        parser.add_argument("--limit", type=int, default=20, help="Máximo de eventos por ciclo.")
        parser.add_argument(
            "--interval",
            type=int,
            default=settings.AI_POLL_SECONDS,
            help="Intervalo entre ciclos em segundos.",
        )

    def handle(self, *args, **options):
        once = options["once"]
        limit = max(1, options["limit"])
        requested_interval = max(10, options["interval"])
        interval = (
            min(requested_interval, settings.AI_ACTIVE_ASSISTANT_POLL_SECONDS)
            if settings.AI_ACTIVE_ASSISTANT_ENABLED
            else requested_interval
        )
        while True:
            recovered = recover_stale_events()
            created = enqueue_due_events()
            active_processed = process_active_order_events(limit=limit)
            remaining = max(0, limit - active_processed)
            regular_processed = process_available_events(limit=remaining)
            processed = active_processed + regular_processed
            expired = expire_stale_recommendations()
            self.stdout.write(
                self.style.SUCCESS(
                    "Central Inteligente: "
                    f"recuperados={recovered}, "
                    f"enfileirados={sum(created.values())}, "
                    f"processados={processed}, "
                    f"ativos={active_processed}, expirados={expired}"
                )
            )
            if once:
                return
            time.sleep(interval)
