from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
    display_name = models.CharField("nome de exibição", max_length=150, blank=True)
    must_change_password = models.BooleanField("deve trocar a senha", default=False)

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self) -> str:
        return self.display_name or self.get_full_name() or self.username


class UserCapabilityOverride(models.Model):
    class Effect(models.TextChoices):
        ALLOW = "allow", "Permitir"
        DENY = "deny", "Remover"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="capability_overrides"
    )
    capability = models.CharField("capacidade", max_length=64)
    effect = models.CharField("efeito", max_length=5, choices=Effect.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "capability"), name="accounts_user_capability_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    capability__in=(
                        "access_dashboard",
                        "view_orders",
                        "create_orders",
                        "edit_orders",
                        "change_order_status",
                        "cancel_orders",
                        "view_requests",
                        "approve_requests",
                        "reject_requests",
                        "request_correction",
                        "view_companies",
                        "manage_companies",
                        "view_products",
                        "manage_products",
                        "view_closings",
                        "review_closings",
                        "export_closings",
                        "view_reports",
                        "view_audit",
                        "access_intelligence",
                        "record_ai_feedback",
                        "manage_attendants",
                        "manage_lower_users",
                        "access_technical_area",
                    )
                ),
                name="accounts_override_capability_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(effect__in=("allow", "deny")),
                name="accounts_override_effect_valid",
            ),
        ]
        indexes = [models.Index(fields=("user",), name="accounts_override_user_idx")]
        ordering = ("capability",)

    def clean(self):
        from .access import CONFIGURABLE_CAPABILITIES, ROOT_USERNAME, Capability

        try:
            capability = Capability(self.capability)
        except ValueError as exc:
            raise ValidationError(
                {"capability": "Capacidade fora do catálogo controlado."}
            ) from exc
        if capability not in CONFIGURABLE_CAPABILITIES:
            raise ValidationError({"capability": "Capacidade protegida pelo sistema."})
        if self.user_id and self.user.username == ROOT_USERNAME:
            raise ValidationError({"user": "A conta raiz não aceita personalizações."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
