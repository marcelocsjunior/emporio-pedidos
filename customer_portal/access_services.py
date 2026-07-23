from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.utils import timezone

from orders.services import record_audit

from .models import CustomerPortalAccess, CustomerPortalAccessRequest

User = get_user_model()
IDEMPOTENCY_WINDOW = timedelta(hours=24)
ABUSE_WINDOW = timedelta(hours=1)
ABUSE_LIMIT = 5
PUBLIC_REQUEST_CREATED = "created"
PUBLIC_REQUEST_DUPLICATE = "duplicate"
PUBLIC_REQUEST_RATE_LIMITED = "rate_limited"
ACTIVE_REQUEST_STATUSES = (
    CustomerPortalAccessRequest.Status.PENDING,
    CustomerPortalAccessRequest.Status.IN_REVIEW,
)


def secure_fingerprint(value: str, *, purpose: str) -> str:
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, f"portal-access:{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def create_public_request(*, cleaned_data: dict, remote_address: str, user_agent: str):
    now = timezone.now()
    document = cleaned_data["document"]
    document_fp = secure_fingerprint(document, purpose="document")
    identity = "|".join((document_fp, cleaned_data["email"], cleaned_data["phone"]))
    idem_fp = secure_fingerprint(identity, purpose="idempotency")
    address_fp = secure_fingerprint(remote_address or "unknown", purpose="network")
    abuse_fp = secure_fingerprint(f"{address_fp}|{document_fp}", purpose="abuse")
    recent = CustomerPortalAccessRequest.objects.filter(
        idempotency_fingerprint=idem_fp,
        status__in=ACTIVE_REQUEST_STATUSES,
        requested_at__gte=now - IDEMPOTENCY_WINDOW,
    ).first()
    if recent:
        return recent, PUBLIC_REQUEST_DUPLICATE

    abuse_count = CustomerPortalAccessRequest.objects.filter(
        models.Q(abuse_metadata__requester=abuse_fp)
        | models.Q(
            document_fingerprint=document_fp,
            abuse_metadata__network=address_fp,
        ),
        requested_at__gte=now - ABUSE_WINDOW,
    ).count()
    if abuse_count >= ABUSE_LIMIT:
        return None, PUBLIC_REQUEST_RATE_LIMITED

    with transaction.atomic():
        access_request = CustomerPortalAccessRequest.objects.create(
            customer_name=cleaned_data["customer_name"],
            entity_type=cleaned_data["entity_type"],
            document_fingerprint=document_fp,
            document_last_four=document[-4:],
            requester_name=cleaned_data["requester_name"],
            email=cleaned_data["email"],
            phone=cleaned_data["phone"],
            message=cleaned_data["message"],
            idempotency_fingerprint=idem_fp,
            abuse_metadata={
                "network": address_fp,
                "requester": abuse_fp,
                "user_agent": secure_fingerprint(user_agent[:300], purpose="agent"),
            },
        )
        record_audit(
            actor=None,
            action="portal_access_request_created",
            entity=access_request,
            payload={"request_id": str(access_request.pk)},
        )
    return access_request, PUBLIC_REQUEST_CREATED


@transaction.atomic
def create_portal_user(*, form, actor):
    user = form.save(commit=False)
    user.set_password(form.cleaned_data["password1"])
    user.must_change_password = True
    user.is_active = True
    user.is_staff = False
    user.is_superuser = False
    user.save()
    access = CustomerPortalAccess.objects.create(
        user=user,
        company=form.cleaned_data["company"],
        active=form.cleaned_data["active"],
        created_by=actor,
    )
    record_audit(
        actor=actor,
        action="customer_portal_user_created",
        entity=user,
        payload={"user_id": str(user.pk), "company_id": str(access.company_id)},
    )
    record_audit(
        actor=actor,
        action="customer_portal_access_linked",
        entity=access,
        payload={"user_id": str(user.pk), "company_id": str(access.company_id)},
    )
    return access


@transaction.atomic
def link_portal_user(*, user, company, actor, active=True):
    access = CustomerPortalAccess.objects.create(
        user=user, company=company, active=active, created_by=actor
    )
    record_audit(
        actor=actor,
        action="customer_portal_access_linked",
        entity=access,
        payload={"user_id": str(user.pk), "company_id": str(company.pk)},
    )
    return access


@transaction.atomic
def set_access_active(*, access, active: bool, actor, reason=""):
    previous = access.active
    access.active = active
    if active:
        access.revoked_by = None
        access.revoked_at = None
        access.revocation_reason = ""
        action = "customer_portal_access_activated"
    else:
        access.revoked_by = actor
        access.revoked_at = timezone.now()
        access.revocation_reason = reason
        action = "customer_portal_access_revoked"
    access.save()
    record_audit(
        actor=actor,
        action=action,
        entity=access,
        payload={
            "user_id": str(access.user_id),
            "company_id": str(access.company_id),
            "previous_status": previous,
            "new_status": active,
            "reason": reason[:300],
        },
    )
    return access


@transaction.atomic
def reset_portal_password(*, access, password: str, actor):
    access.user.set_password(password)
    access.user.must_change_password = True
    access.user.save(update_fields=("password", "must_change_password"))
    record_audit(
        actor=actor,
        action="customer_portal_password_reset_by_admin",
        entity=access,
        payload={"user_id": str(access.user_id), "company_id": str(access.company_id)},
    )


@transaction.atomic
def start_access_request_review(*, access_request, actor, company=None):
    if access_request.status not in {
        CustomerPortalAccessRequest.Status.PENDING,
        CustomerPortalAccessRequest.Status.IN_REVIEW,
    }:
        raise ValueError("Esta solicitação já possui decisão final.")
    previous = access_request.status
    access_request.status = CustomerPortalAccessRequest.Status.IN_REVIEW
    access_request.reviewed_by = actor
    access_request.reviewed_at = timezone.now()
    if company:
        access_request.company = company
    access_request.save()
    record_audit(
        actor=actor,
        action="portal_access_request_review_started",
        entity=access_request,
        payload={
            "request_id": str(access_request.pk),
            "previous_status": previous,
            "new_status": access_request.status,
            "company_id": str(company.pk) if company else None,
        },
    )


@transaction.atomic
def approve_access_request(*, access_request, company, user, actor, confirmed: bool):
    if not confirmed or not company or not user:
        raise ValueError("A aprovação exige confirmação, empresa e usuário.")
    if access_request.status not in {
        CustomerPortalAccessRequest.Status.PENDING,
        CustomerPortalAccessRequest.Status.IN_REVIEW,
    }:
        raise ValueError("Esta solicitação já possui decisão final.")
    access = CustomerPortalAccess.objects.filter(user=user).first()
    if access and access.company_id != company.pk:
        raise ValueError("O usuário já possui vínculo com outra empresa.")
    if not access:
        access = link_portal_user(user=user, company=company, actor=actor)
    elif not access.active:
        set_access_active(access=access, active=True, actor=actor)
    access_request.company = company
    access_request.status = CustomerPortalAccessRequest.Status.APPROVED
    access_request.reviewed_by = actor
    access_request.reviewed_at = timezone.now()
    access_request.save()
    record_audit(
        actor=actor,
        action="portal_access_request_approved",
        entity=access_request,
        payload={
            "request_id": str(access_request.pk),
            "company_id": str(company.pk),
            "user_id": str(user.pk),
        },
    )
    return access


@transaction.atomic
def reject_access_request(*, access_request, reason: str, actor):
    if access_request.status not in {
        CustomerPortalAccessRequest.Status.PENDING,
        CustomerPortalAccessRequest.Status.IN_REVIEW,
    }:
        raise ValueError("Esta solicitação já possui decisão final.")
    access_request.status = CustomerPortalAccessRequest.Status.REJECTED
    access_request.decision_notes = reason
    access_request.reviewed_by = actor
    access_request.reviewed_at = timezone.now()
    access_request.save()
    record_audit(
        actor=actor,
        action="portal_access_request_rejected",
        entity=access_request,
        payload={"request_id": str(access_request.pk), "reason": reason[:300]},
    )
