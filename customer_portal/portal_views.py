from __future__ import annotations

import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from .forms import CustomerRequestForm, CustomerRequestItemFormSet
from .mixins import CustomerPortalAccessMixin
from .models import CustomerOrderRequest
from .services import (
    CANCELLABLE_STATUSES,
    EDITABLE_STATUSES,
    cancel_request,
    create_request_from_forms,
    submit_request,
    update_request_from_forms,
)


class PortalRequestListView(CustomerPortalAccessMixin, ListView):
    model = CustomerOrderRequest
    template_name = "customer_portal/request_list.html"
    context_object_name = "customer_requests"
    paginate_by = 30

    def get_queryset(self):
        return (
            CustomerOrderRequest.objects.filter(
                company=self.portal_access.company,
                requested_by=self.request.user,
            )
            .select_related("delivery_location", "converted_order")
            .prefetch_related("items")
        )


class PortalRequestCreateView(CustomerPortalAccessMixin, View):
    template_name = "customer_portal/request_form.html"
    session_key = "customer_request_creation_key"

    def get(self, request: HttpRequest) -> HttpResponse:
        creation_key = uuid.uuid4().hex
        request.session[self.session_key] = creation_key
        draft = CustomerOrderRequest(
            company=self.portal_access.company,
            requested_by=request.user,
        )
        form = CustomerRequestForm(
            instance=draft,
            company=self.portal_access.company,
            initial={
                "creation_key": creation_key,
                "delivery_date": timezone.localdate(),
            },
        )
        formset = CustomerRequestItemFormSet(instance=draft, prefix="items")
        return render(
            request,
            self.template_name,
            {"form": form, "formset": formset, "creating": True},
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        creation_key = request.POST.get("creation_key", "").strip()
        existing = (
            CustomerOrderRequest.objects.filter(
                creation_key=creation_key,
                company=self.portal_access.company,
                requested_by=request.user,
            ).first()
            if creation_key
            else None
        )
        if existing:
            messages.info(request, "A solicitação já havia sido salva; duplicidade ignorada.")
            return redirect("customer_portal:request-detail", pk=existing.pk)

        draft = CustomerOrderRequest(
            company=self.portal_access.company,
            requested_by=request.user,
        )
        form = CustomerRequestForm(
            request.POST,
            instance=draft,
            company=self.portal_access.company,
        )
        formset = CustomerRequestItemFormSet(
            request.POST,
            instance=draft,
            prefix="items",
        )
        forms_valid = form.is_valid() and formset.is_valid()
        expected_key = request.session.get(self.session_key)

        if forms_valid and creation_key != expected_key:
            form.add_error("creation_key", "A sessão expirou. Reabra a nova solicitação.")
            forms_valid = False

        if forms_valid:
            customer_request, created = create_request_from_forms(
                request_form=form,
                item_formset=formset,
                actor=request.user,
                company=self.portal_access.company,
                creation_key=creation_key,
            )
            request.session.pop(self.session_key, None)
            if created:
                messages.success(
                    request,
                    "Rascunho salvo. Revise e envie para o Atendimento.",
                )
            else:
                messages.info(request, "Solicitação já existente; repetição ignorada.")
            return redirect("customer_portal:request-detail", pk=customer_request.pk)

        return render(
            request,
            self.template_name,
            {"form": form, "formset": formset, "creating": True},
        )


class PortalRequestUpdateView(CustomerPortalAccessMixin, View):
    template_name = "customer_portal/request_form.html"

    def get_object(self, pk) -> CustomerOrderRequest:
        return get_object_or_404(
            CustomerOrderRequest,
            pk=pk,
            company=self.portal_access.company,
            requested_by=self.request.user,
        )

    def get(self, request: HttpRequest, pk) -> HttpResponse:
        customer_request = self.get_object(pk)
        if customer_request.status not in EDITABLE_STATUSES:
            messages.error(request, "Esta solicitação não pode mais ser editada.")
            return redirect("customer_portal:request-detail", pk=pk)

        form = CustomerRequestForm(
            instance=customer_request,
            company=self.portal_access.company,
            initial={"creation_key": customer_request.creation_key},
        )
        formset = CustomerRequestItemFormSet(
            instance=customer_request,
            prefix="items",
        )
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "creating": False,
                "customer_request": customer_request,
            },
        )

    def post(self, request: HttpRequest, pk) -> HttpResponse:
        customer_request = self.get_object(pk)
        form = CustomerRequestForm(
            request.POST,
            instance=customer_request,
            company=self.portal_access.company,
        )
        formset = CustomerRequestItemFormSet(
            request.POST,
            instance=customer_request,
            prefix="items",
        )

        if form.is_valid() and formset.is_valid():
            try:
                customer_request = update_request_from_forms(
                    customer_request=customer_request,
                    request_form=form,
                    item_formset=formset,
                    actor=request.user,
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Solicitação atualizada.")
                return redirect("customer_portal:request-detail", pk=customer_request.pk)

        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "creating": False,
                "customer_request": customer_request,
            },
        )


class PortalRequestDetailView(CustomerPortalAccessMixin, DetailView):
    model = CustomerOrderRequest
    template_name = "customer_portal/request_detail.html"
    context_object_name = "customer_request"

    def get_queryset(self):
        return (
            CustomerOrderRequest.objects.filter(
                company=self.portal_access.company,
                requested_by=self.request.user,
            )
            .select_related("delivery_location", "converted_order")
            .prefetch_related("items")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_edit"] = self.object.status in EDITABLE_STATUSES
        context["can_cancel"] = self.object.status in CANCELLABLE_STATUSES
        return context


class PortalRequestSubmitView(CustomerPortalAccessMixin, View):
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk) -> HttpResponse:
        customer_request = get_object_or_404(
            CustomerOrderRequest,
            pk=pk,
            company=self.portal_access.company,
            requested_by=request.user,
        )
        try:
            submit_request(request_id=customer_request.pk, actor=request.user)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                f"Solicitação {customer_request.protocol} enviada para conferência.",
            )
        return redirect("customer_portal:request-detail", pk=pk)


class PortalRequestCancelView(CustomerPortalAccessMixin, View):
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk) -> HttpResponse:
        customer_request = get_object_or_404(
            CustomerOrderRequest,
            pk=pk,
            company=self.portal_access.company,
            requested_by=request.user,
        )
        try:
            cancel_request(request_id=customer_request.pk, actor=request.user)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Solicitação cancelada.")
        return redirect("customer_portal:request-detail", pk=pk)
