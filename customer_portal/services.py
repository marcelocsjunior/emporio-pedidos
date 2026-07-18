from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from orders.models import Order, OrderItem
from orders.services import record_audit

from .models import CustomerOrderRequest

EDITABLE_STATUSES = {
    CustomerOrderRequest.Status.DRAFT,
    CustomerOrderRequest.Status.CORRECTION_REQUESTED,
}

CANCELLABLE_STATUSES = {
    CustomerOrderRequest.Status.DRAFT,
    CustomerOrderRequest.Status.SUBMITTED,
    CustomerOrderRequest.Status.IN_REVIEW,
    CustomerOrderRequest.Status.CORRECTION_REQUESTED,
}

REVIEWABLE_STATUSES = {
    CustomerOrderRequest.Status.SUBMITTED,
    CustomerOrderRequest.Status.IN_REVIEW,
}


def _request_snapshot(customer_request: CustomerOrderRequest) -> dict[str, str]:
    return {
        "company_id": str(customer_request.company_id),
        "delivery_date": customer_request.delivery_date.isoformat(),
        "delivery_time": (
            customer_request.delivery_time.isoformat() if customer_request.delivery_time else ""
        ),
        "delivery_location_id": str(customer_request.delivery_location_id),
        "status": customer_request.status,
        "total_amount": str(customer_request.total_amount),
    }


def _save_items(*, formset, customer_request: CustomerOrderRequest) -> tuple[list[str], list[str]]:
    formset.instance = customer_request
    items = formset.save(commit=False)
    deleted_ids = [str(item.pk) for item in getattr(formset, "deleted_objects", ())]

    for item in getattr(formset, "deleted_objects", ()):
        item.delete()

    saved_ids: list[str] = []
    for item in items:
        item.request = customer_request
        item.unit_price = Decimal(item.product.unit_price)
        item.full_clean()
        item.save()
        saved_ids.append(str(item.pk))

    formset.save_m2m()
    customer_request.recalculate_total()
    return saved_ids, deleted_ids


def create_request_from_forms(
    *,
    request_form,
    item_formset,
    actor,
    company,
    creation_key: str,
) -> tuple[CustomerOrderRequest, bool]:
    existing = CustomerOrderRequest.objects.filter(creation_key=creation_key).first()
    if existing:
        return existing, False

    try:
        with transaction.atomic():
            customer_request = request_form.save(commit=False)
            customer_request.creation_key = creation_key
            customer_request.company = company
            customer_request.requested_by = actor
            customer_request.status = CustomerOrderRequest.Status.DRAFT
            customer_request.full_clean()
            customer_request.save()
            saved_ids, _ = _save_items(
                formset=item_formset,
                customer_request=customer_request,
            )
            customer_request.refresh_from_db()
            record_audit(
                actor=actor,
                action="customer_request.created",
                entity=customer_request,
                payload={
                    **_request_snapshot(customer_request),
                    "item_ids": saved_ids,
                    "item_count": customer_request.items.count(),
                },
            )
            return customer_request, True
    except IntegrityError:
        existing = CustomerOrderRequest.objects.filter(creation_key=creation_key).first()
        if existing:
            return existing, False
        raise


@transaction.atomic
def update_request_from_forms(*, customer_request, request_form, item_formset, actor):
    locked = CustomerOrderRequest.objects.select_for_update().get(pk=customer_request.pk)
    if locked.status not in EDITABLE_STATUSES:
        raise ValidationError("Esta solicitação não pode mais ser editada.")

    before = _request_snapshot(locked)
    for field in ("delivery_date", "delivery_time", "delivery_location", "notes"):
        setattr(locked, field, request_form.cleaned_data[field])
    locked.review_notes = ""
    locked.full_clean()
    locked.save()

    saved_ids, deleted_ids = _save_items(
        formset=item_formset,
        customer_request=locked,
    )
    locked.refresh_from_db()
    record_audit(
        actor=actor,
        action="customer_request.updated",
        entity=locked,
        payload={
            "before": before,
            "after": _request_snapshot(locked),
            "saved_item_ids": saved_ids,
            "deleted_item_ids": deleted_ids,
        },
    )
    return locked


@transaction.atomic
def submit_request(*, request_id, actor) -> CustomerOrderRequest:
    customer_request = (
        CustomerOrderRequest.objects.select_for_update()
        .select_related("company", "delivery_location")
        .get(pk=request_id)
    )

    if customer_request.requested_by_id != actor.pk:
        raise ValidationError("Usuário não autorizado para esta solicitação.")
    if customer_request.status == CustomerOrderRequest.Status.SUBMITTED:
        return customer_request
    if customer_request.status not in EDITABLE_STATUSES:
        raise ValidationError("Esta solicitação não pode ser enviada neste status.")
    if not customer_request.company.active:
        raise ValidationError("A empresa está inativa.")
    if (
        not customer_request.delivery_location.active
        or customer_request.delivery_location.company_id != customer_request.company_id
    ):
        raise ValidationError("O local de entrega está inativo ou não pertence à empresa.")

    items = list(customer_request.items.select_related("product"))
    if not items:
        raise ValidationError("Adicione ao menos um item antes de enviar.")

    for item in items:
        if not item.product.active:
            raise ValidationError(f"O produto {item.product_name} está inativo.")
        item.unit_price = Decimal(item.product.unit_price)
        item.save(update_fields=("unit_price", "product_name", "line_total", "updated_at"))

    customer_request.recalculate_total()
    customer_request.refresh_from_db()
    if customer_request.total_amount <= 0:
        raise ValidationError("A solicitação precisa ter valor total maior que zero.")

    customer_request.status = CustomerOrderRequest.Status.SUBMITTED
    customer_request.delivery_address_snapshot = customer_request.delivery_location.full_address
    customer_request.submitted_at = timezone.now()
    customer_request.review_notes = ""
    customer_request.reviewed_by = None
    customer_request.reviewed_at = None
    customer_request.full_clean()
    customer_request.save()

    record_audit(
        actor=actor,
        action="customer_request.submitted",
        entity=customer_request,
        payload=_request_snapshot(customer_request),
    )
    return customer_request


@transaction.atomic
def cancel_request(*, request_id, actor) -> CustomerOrderRequest:
    customer_request = CustomerOrderRequest.objects.select_for_update().get(pk=request_id)
    if customer_request.requested_by_id != actor.pk:
        raise ValidationError("Usuário não autorizado para esta solicitação.")
    if customer_request.status == CustomerOrderRequest.Status.CANCELLED:
        return customer_request
    if customer_request.status not in CANCELLABLE_STATUSES:
        raise ValidationError("A solicitação não pode mais ser cancelada.")

    previous = customer_request.status
    customer_request.status = CustomerOrderRequest.Status.CANCELLED
    customer_request.cancelled_at = timezone.now()
    customer_request.save(update_fields=("status", "cancelled_at", "updated_at"))
    record_audit(
        actor=actor,
        action="customer_request.cancelled",
        entity=customer_request,
        payload={"from": previous, "to": customer_request.status},
    )
    return customer_request


@transaction.atomic
def request_correction(*, request_id, actor, reason: str) -> CustomerOrderRequest:
    customer_request = CustomerOrderRequest.objects.select_for_update().get(pk=request_id)
    if customer_request.status not in REVIEWABLE_STATUSES:
        raise ValidationError("A solicitação não está disponível para correção.")

    previous = customer_request.status
    customer_request.status = CustomerOrderRequest.Status.CORRECTION_REQUESTED
    customer_request.review_notes = reason.strip()
    customer_request.reviewed_by = actor
    customer_request.reviewed_at = timezone.now()
    customer_request.save(
        update_fields=(
            "status",
            "review_notes",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        )
    )
    record_audit(
        actor=actor,
        action="customer_request.correction_requested",
        entity=customer_request,
        payload={"from": previous, "to": customer_request.status, "reason": reason},
    )
    return customer_request


@transaction.atomic
def reject_request(*, request_id, actor, reason: str) -> CustomerOrderRequest:
    customer_request = CustomerOrderRequest.objects.select_for_update().get(pk=request_id)
    if customer_request.status not in REVIEWABLE_STATUSES:
        raise ValidationError("A solicitação não está disponível para rejeição.")

    previous = customer_request.status
    customer_request.status = CustomerOrderRequest.Status.REJECTED
    customer_request.review_notes = reason.strip()
    customer_request.reviewed_by = actor
    customer_request.reviewed_at = timezone.now()
    customer_request.save(
        update_fields=(
            "status",
            "review_notes",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        )
    )
    record_audit(
        actor=actor,
        action="customer_request.rejected",
        entity=customer_request,
        payload={"from": previous, "to": customer_request.status, "reason": reason},
    )
    return customer_request


@transaction.atomic
def approve_and_convert_request(*, request_id, actor) -> tuple[Order, bool]:
    customer_request = (
        CustomerOrderRequest.objects.select_for_update()
        .select_related("company", "delivery_location")
        .get(pk=request_id)
    )

    if customer_request.converted_order_id:
        return customer_request.converted_order, False
    if customer_request.status not in REVIEWABLE_STATUSES:
        raise ValidationError("A solicitação não está disponível para aprovação.")
    if not customer_request.company.active:
        raise ValidationError("A empresa está inativa.")

    request_items = list(customer_request.items.select_related("product"))
    if not request_items or customer_request.total_amount <= 0:
        raise ValidationError("A solicitação não possui itens válidos.")

    now = timezone.now()
    previous = customer_request.status
    customer_request.status = CustomerOrderRequest.Status.APPROVED
    customer_request.reviewed_by = actor
    customer_request.reviewed_at = now
    customer_request.approved_at = now
    customer_request.review_notes = ""
    customer_request.save(
        update_fields=(
            "status",
            "reviewed_by",
            "reviewed_at",
            "approved_at",
            "review_notes",
            "updated_at",
        )
    )
    record_audit(
        actor=actor,
        action="customer_request.approved",
        entity=customer_request,
        payload={"from": previous, "to": customer_request.status},
    )

    creation_key = f"portal:{customer_request.pk}"
    order = Order.objects.filter(creation_key=creation_key).first()
    created = order is None

    if order is None:
        order = Order(
            creation_key=creation_key,
            company=customer_request.company,
            order_date=timezone.localdate(),
            delivery_date=customer_request.delivery_date,
            delivery_time=customer_request.delivery_time,
            delivery_location=(
                customer_request.delivery_address_snapshot
                or customer_request.delivery_location.full_address
            ),
            notes=customer_request.notes,
            status=Order.Status.PENDING,
            created_by=actor,
            updated_by=actor,
        )
        order.full_clean()
        order.save()

        for request_item in request_items:
            OrderItem.objects.create(
                order=order,
                product=request_item.product,
                quantity=request_item.quantity,
                unit_price=request_item.unit_price,
            )
        order.refresh_from_db()
        record_audit(
            actor=actor,
            action="order.created_from_customer_request",
            entity=order,
            payload={
                "customer_request_id": str(customer_request.pk),
                "customer_request_protocol": customer_request.protocol,
                "total_amount": str(order.total_amount),
                "item_count": order.items.count(),
            },
        )

    customer_request.converted_order = order
    customer_request.status = CustomerOrderRequest.Status.CONVERTED
    customer_request.save(update_fields=("converted_order", "status", "updated_at"))
    record_audit(
        actor=actor,
        action="customer_request.converted",
        entity=customer_request,
        payload={
            "order_id": str(order.pk),
            "order_number": order.number,
            "created": created,
        },
    )
    return order, created


def find_possible_duplicates(customer_request: CustomerOrderRequest) -> dict[str, list]:
    request_candidates = (
        CustomerOrderRequest.objects.filter(
            company_id=customer_request.company_id,
            delivery_date=customer_request.delivery_date,
            total_amount=customer_request.total_amount,
            status__in=(
                CustomerOrderRequest.Status.SUBMITTED,
                CustomerOrderRequest.Status.IN_REVIEW,
                CustomerOrderRequest.Status.APPROVED,
                CustomerOrderRequest.Status.CONVERTED,
            ),
        )
        .exclude(pk=customer_request.pk)
        .order_by("-created_at")[:10]
    )

    order_candidates = (
        Order.objects.filter(
            company_id=customer_request.company_id,
            delivery_date=customer_request.delivery_date,
            total_amount=customer_request.total_amount,
        )
        .exclude(status=Order.Status.CANCELLED)
        .order_by("-created_at")[:10]
    )

    return {
        "requests": list(request_candidates),
        "orders": list(order_candidates),
    }
