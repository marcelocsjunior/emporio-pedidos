from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from orders.services import record_audit

from .models import CustomerOrderRequest


@transaction.atomic
def start_review(*, request_id, actor) -> CustomerOrderRequest:
    customer_request = CustomerOrderRequest.objects.select_for_update().get(pk=request_id)
    if customer_request.status == CustomerOrderRequest.Status.IN_REVIEW:
        return customer_request
    if customer_request.status != CustomerOrderRequest.Status.SUBMITTED:
        raise ValidationError("A solicitação não está disponível para iniciar análise.")

    customer_request.status = CustomerOrderRequest.Status.IN_REVIEW
    customer_request.reviewed_by = actor
    customer_request.reviewed_at = timezone.now()
    customer_request.save(
        update_fields=("status", "reviewed_by", "reviewed_at", "updated_at")
    )
    record_audit(
        actor=actor,
        action="customer_request.review_started",
        entity=customer_request,
        payload={"from": CustomerOrderRequest.Status.SUBMITTED, "to": customer_request.status},
    )
    return customer_request
