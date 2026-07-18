from __future__ import annotations

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from orders.models import AuditEvent, Company


@receiver(pre_save, sender=Company, dispatch_uid="intelligence.capture_company_data_context")
def capture_company_data_context(sender, instance: Company, **kwargs) -> None:
    if not instance.pk:
        instance._previous_is_demo = None
        return
    instance._previous_is_demo = (
        sender.objects.filter(pk=instance.pk).values_list("is_demo", flat=True).first()
    )


@receiver(post_save, sender=Company, dispatch_uid="intelligence.audit_company_data_context")
def audit_company_data_context(sender, instance: Company, created: bool, **kwargs) -> None:
    previous = getattr(instance, "_previous_is_demo", None)
    if created and not instance.is_demo:
        return
    if not created and previous == instance.is_demo:
        return
    AuditEvent.objects.create(
        actor=None,
        action=(
            "company.data_context_assigned" if created else "company.data_context_changed"
        ),
        entity_type=instance._meta.label_lower,
        entity_id=str(instance.pk),
        payload={"from": previous, "to": instance.is_demo},
    )
