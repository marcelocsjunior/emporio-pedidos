from django.apps import AppConfig


class IntelligenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "intelligence"
    verbose_name = "Central Inteligente"

    def ready(self) -> None:
        from . import signals  # noqa: F401
