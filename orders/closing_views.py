from __future__ import annotations

import csv
import uuid
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from .closing_forms import ClosingGenerateForm, ClosingNotesForm
from .closing_services import (
    allowed_closing_statuses_for_user,
    build_whatsapp_link,
    change_closing_status,
    closing_orders_queryset,
    generate_or_recalculate_closing,
    update_closing_notes,
)
from .models import AuditEvent, Company, MonthlyClosing

AUDIT_LABELS = {
    "closing.generated": "Fechamento gerado",
    "closing.recalculated": "Fechamento recalculado",
    "closing.status_changed": "Status do fechamento alterado",
    "closing.notes_updated": "Observações atualizadas",
}


class ClosingPermissionMixin(LoginRequiredMixin, PermissionRequiredMixin):
    raise_exception = True


class ClosingListView(ClosingPermissionMixin, ListView):
    permission_required = "orders.view_monthlyclosing"
    model = MonthlyClosing
    template_name = "orders/closing_list.html"
    context_object_name = "closings"
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related("company", "generated_by")
        company_id = self.request.GET.get("company", "").strip()
        status = self.request.GET.get("status", "").strip()
        reference_month = self.request.GET.get("reference_month", "").strip()
        if company_id:
            try:
                company_uuid = uuid.UUID(company_id)
            except ValueError:
                messages.warning(self.request, "Empresa inválida; filtro ignorado.")
            else:
                queryset = queryset.filter(company_id=company_uuid)
        if status in MonthlyClosing.Status.values:
            queryset = queryset.filter(status=status)
        if reference_month:
            try:
                month = datetime.strptime(reference_month, "%Y-%m").date().replace(day=1)
            except ValueError:
                messages.warning(self.request, "Mês de referência inválido; filtro ignorado.")
            else:
                queryset = queryset.filter(reference_month=month)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "generate_form": ClosingGenerateForm(
                    initial={"reference_month": timezone.localdate().replace(day=1)}
                ),
                "companies": Company.objects.order_by("name"),
                "status_choices": MonthlyClosing.Status.choices,
            }
        )
        return context


class ClosingGenerateView(ClosingPermissionMixin, View):
    permission_required = "orders.add_monthlyclosing"
    http_method_names = ("post",)

    def post(self, request: HttpRequest) -> HttpResponse:
        form = ClosingGenerateForm(request.POST)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect("closing-list")
        company = form.cleaned_data["company"]
        reference_month = form.cleaned_data["reference_month"]
        try:
            closing = generate_or_recalculate_closing(
                company_id=company.pk,
                reference_month=reference_month,
                actor=request.user,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("closing-list")
        messages.success(request, f"Fechamento de {company.name} gerado para conferência.")
        return redirect("closing-detail", pk=closing.pk)


class ClosingDetailView(ClosingPermissionMixin, DetailView):
    permission_required = "orders.view_monthlyclosing"
    model = MonthlyClosing
    template_name = "orders/closing_detail.html"
    context_object_name = "closing"

    def get_queryset(self):
        return super().get_queryset().select_related("company", "generated_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        allowed = allowed_closing_statuses_for_user(self.request.user, self.object)
        events = AuditEvent.objects.filter(
            entity_type="orders.monthlyclosing",
            entity_id=str(self.object.pk),
        ).select_related("actor")[:50]
        context.update(
            {
                "orders": closing_orders_queryset(self.object),
                "allowed_statuses": [
                    (value, label)
                    for value, label in MonthlyClosing.Status.choices
                    if value in allowed
                ],
                "notes_form": ClosingNotesForm(instance=self.object),
                "whatsapp_link": build_whatsapp_link(self.object),
                "audit_rows": [
                    {
                        "label": AUDIT_LABELS.get(event.action, "Atualização registrada"),
                        "created_at": event.created_at,
                        "actor": event.actor,
                    }
                    for event in events
                ],
                "can_recalculate": self.request.user.has_perm(
                    "orders.change_monthlyclosing"
                )
                and self.object.status
                not in {
                    MonthlyClosing.Status.VALIDATED,
                    MonthlyClosing.Status.INVOICED,
                },
            }
        )
        return context


class ClosingRecalculateView(ClosingPermissionMixin, View):
    permission_required = "orders.change_monthlyclosing"
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk) -> HttpResponse:
        closing = get_object_or_404(MonthlyClosing, pk=pk)
        try:
            generate_or_recalculate_closing(
                company_id=closing.company_id,
                reference_month=closing.reference_month,
                actor=request.user,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Fechamento recalculado com os pedidos entregues do mês.")
        return redirect("closing-detail", pk=pk)


class ClosingStatusUpdateView(ClosingPermissionMixin, View):
    permission_required = "orders.change_monthlyclosing"
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk) -> HttpResponse:
        closing = get_object_or_404(MonthlyClosing, pk=pk)
        new_status = request.POST.get("new_status", "").strip()
        reason = request.POST.get("reason", "").strip()[:255]
        allowed = allowed_closing_statuses_for_user(request.user, closing)
        if new_status not in allowed:
            messages.error(request, "Esta transição de fechamento não está disponível.")
            return redirect("closing-detail", pk=pk)
        try:
            updated = change_closing_status(
                closing_id=closing.pk,
                new_status=new_status,
                actor=request.user,
                reason=reason,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, f"Fechamento atualizado para {updated.get_status_display()}.")
        return redirect("closing-detail", pk=pk)


class ClosingNotesUpdateView(ClosingPermissionMixin, View):
    permission_required = "orders.change_monthlyclosing"
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk) -> HttpResponse:
        closing = get_object_or_404(MonthlyClosing, pk=pk)
        form = ClosingNotesForm(request.POST, instance=closing)
        if not form.is_valid():
            messages.error(request, "Não foi possível salvar as observações do fechamento.")
            return redirect("closing-detail", pk=pk)
        update_closing_notes(
            closing=closing,
            notes=form.cleaned_data["notes"],
            actor=request.user,
        )
        messages.success(request, "Observações do fechamento atualizadas.")
        return redirect("closing-detail", pk=pk)


def _csv_safe(value: object) -> str:
    text = str(value or "")
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


class ClosingCsvExportView(ClosingPermissionMixin, View):
    permission_required = "orders.view_monthlyclosing"
    http_method_names = ("get",)

    def get(self, request: HttpRequest, pk) -> HttpResponse:
        closing = get_object_or_404(
            MonthlyClosing.objects.select_related("company"),
            pk=pk,
        )
        filename = f"fechamento-{closing.reference_month:%Y-%m}-{closing.company.code}.csv"
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("\ufeff")
        writer = csv.writer(response, delimiter=";", lineterminator="\n")
        writer.writerow(
            [
                "Pedido",
                "Empresa",
                "Data do pedido",
                "Data da entrega",
                "Horário",
                "Quantidade de itens",
                "Valor total",
                "Status",
            ]
        )
        for order in closing_orders_queryset(closing):
            item_quantity = sum(item.quantity for item in order.items.all())
            writer.writerow(
                [
                    _csv_safe(order.number),
                    _csv_safe(order.company.name),
                    order.order_date.strftime("%d/%m/%Y"),
                    order.delivery_date.strftime("%d/%m/%Y"),
                    order.delivery_time.strftime("%H:%M") if order.delivery_time else "",
                    item_quantity,
                    f"{order.total_amount:.2f}".replace(".", ","),
                    order.get_status_display(),
                ]
            )
        return response
