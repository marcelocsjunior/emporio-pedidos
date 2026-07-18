from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import redirect
from django.views import View
from django.views.generic import DetailView, ListView

from .forms import ReviewReasonForm
from .mixins import ReviewPermissionMixin
from .models import CustomerOrderRequest
from .services import (
    REVIEWABLE_STATUSES,
    approve_and_convert_request,
    find_possible_duplicates,
    reject_request,
    request_correction,
)


class RequestQueueView(ReviewPermissionMixin, ListView):
    model = CustomerOrderRequest
    template_name = "customer_portal/request_queue.html"
    context_object_name = "customer_requests"
    paginate_by = 40

    def get_queryset(self):
        queryset = CustomerOrderRequest.objects.select_related(
            "company",
            "requested_by",
            "delivery_location",
            "converted_order",
        )
        status = self.request.GET.get("status", "").strip()
        query = self.request.GET.get("q", "").strip()
        delivery_date = self.request.GET.get("delivery_date", "").strip()

        if status in CustomerOrderRequest.Status.values:
            queryset = queryset.filter(status=status)
        else:
            queryset = queryset.filter(
                status__in=(
                    CustomerOrderRequest.Status.SUBMITTED,
                    CustomerOrderRequest.Status.IN_REVIEW,
                    CustomerOrderRequest.Status.CORRECTION_REQUESTED,
                )
            )
        if query:
            queryset = queryset.filter(
                Q(protocol__icontains=query)
                | Q(company__name__icontains=query)
                | Q(requested_by__username__icontains=query)
            )
        if delivery_date:
            try:
                queryset = queryset.filter(delivery_date=date.fromisoformat(delivery_date))
            except ValueError:
                messages.warning(self.request, "Data inválida; filtro ignorado.")
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = CustomerOrderRequest.Status.choices
        return context


class RequestReviewView(ReviewPermissionMixin, DetailView):
    model = CustomerOrderRequest
    template_name = "customer_portal/request_review.html"
    context_object_name = "customer_request"

    def get_queryset(self):
        return CustomerOrderRequest.objects.select_related(
            "company",
            "requested_by",
            "delivery_location",
            "converted_order",
            "reviewed_by",
        ).prefetch_related("items")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["reviewable"] = self.object.status in REVIEWABLE_STATUSES
        context["reason_form"] = ReviewReasonForm()
        context["duplicates"] = find_possible_duplicates(self.object)
        return context


class RequestCorrectionView(ReviewPermissionMixin, View):
    http_method_names = ("post",)

    def post(self, request, pk):
        form = ReviewReasonForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Informe a justificativa para solicitar correção.")
            return redirect("customer_portal:request-review", pk=pk)
        try:
            request_correction(
                request_id=pk,
                actor=request.user,
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Solicitação devolvida ao cliente para correção.")
        return redirect("customer_portal:request-review", pk=pk)


class RequestRejectView(ReviewPermissionMixin, View):
    http_method_names = ("post",)

    def post(self, request, pk):
        form = ReviewReasonForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Informe a justificativa da rejeição.")
            return redirect("customer_portal:request-review", pk=pk)
        try:
            reject_request(
                request_id=pk,
                actor=request.user,
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Solicitação rejeitada.")
        return redirect("customer_portal:request-review", pk=pk)


class RequestApproveView(ReviewPermissionMixin, View):
    http_method_names = ("post",)

    def post(self, request, pk):
        try:
            order, created = approve_and_convert_request(
                request_id=pk,
                actor=request.user,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("customer_portal:request-review", pk=pk)

        if created:
            messages.success(request, f"Solicitação aprovada e pedido {order.number} criado.")
        else:
            messages.info(request, f"Pedido {order.number} já existia; duplicidade evitada.")
        return redirect("customer_portal:request-review", pk=pk)
