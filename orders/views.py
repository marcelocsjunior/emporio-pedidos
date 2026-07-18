from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from .access import allowed_statuses_for_user
from .models import AuditEvent, Company, MonthlyClosing, Order, Product
from .services import change_order_status


class SecurePermissionMixin(LoginRequiredMixin, PermissionRequiredMixin):
    raise_exception = True


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "orders/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        today_orders = Order.objects.filter(delivery_date=today)
        status_cards = []
        for value, label in Order.Status.choices:
            queryset = today_orders.filter(status=value)
            status_cards.append(
                {
                    "value": value,
                    "label": label,
                    "count": queryset.count(),
                    "amount": queryset.aggregate(total=Sum("total_amount"))["total"] or 0,
                }
            )

        context.update(
            {
                "today": today,
                "active_companies": Company.objects.filter(active=True).count(),
                "active_products": Product.objects.filter(active=True).count(),
                "today_order_count": today_orders.count(),
                "today_total": today_orders.exclude(status=Order.Status.CANCELLED).aggregate(
                    total=Sum("total_amount")
                )["total"]
                or 0,
                "status_cards": status_cards,
                "recent_orders": Order.objects.select_related("company").order_by(
                    "-created_at"
                )[:8],
                "pending_closings": MonthlyClosing.objects.filter(
                    status__in=(
                        MonthlyClosing.Status.PENDING,
                        MonthlyClosing.Status.TO_REVIEW,
                    )
                ).count(),
            }
        )
        return context


class SearchableListMixin:
    search_fields: tuple[str, ...] = ()

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get("q", "").strip()
        if query and self.search_fields:
            filters = Q()
            for field in self.search_fields:
                filters |= Q(**{f"{field}__icontains": query})
            queryset = queryset.filter(filters)
        return queryset


class CompanyListView(SecurePermissionMixin, SearchableListMixin, ListView):
    permission_required = "orders.view_company"
    model = Company
    template_name = "orders/company_list.html"
    context_object_name = "companies"
    paginate_by = 30
    search_fields = ("code", "name", "responsible_name", "city", "phone")


class ProductListView(SecurePermissionMixin, SearchableListMixin, ListView):
    permission_required = "orders.view_product"
    model = Product
    template_name = "orders/product_list.html"
    context_object_name = "products"
    paginate_by = 30
    search_fields = ("code", "name", "category")


class OrderListView(SecurePermissionMixin, SearchableListMixin, ListView):
    permission_required = "orders.view_order"
    model = Order
    template_name = "orders/order_list.html"
    context_object_name = "orders"
    paginate_by = 40
    search_fields = ("number", "company__name", "delivery_location", "notes")

    def get_queryset(self):
        queryset = super().get_queryset().select_related("company")
        status = self.request.GET.get("status", "").strip()
        delivery_date = self.request.GET.get("delivery_date", "").strip()
        if status in Order.Status.values:
            queryset = queryset.filter(status=status)
        if delivery_date:
            try:
                queryset = queryset.filter(delivery_date=date.fromisoformat(delivery_date))
            except ValueError:
                messages.warning(self.request, "Data de entrega inválida; filtro ignorado.")
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = Order.Status.choices
        return context


class OrderDetailView(SecurePermissionMixin, DetailView):
    permission_required = "orders.view_order"
    model = Order
    template_name = "orders/order_detail.html"
    context_object_name = "order"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("company", "created_by", "updated_by")
            .prefetch_related("items__product", "status_history__changed_by")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        allowed = allowed_statuses_for_user(self.request.user, self.object)
        context["allowed_statuses"] = [
            (value, label) for value, label in Order.Status.choices if value in allowed
        ]
        return context


class OrderStatusUpdateView(LoginRequiredMixin, View):
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk) -> HttpResponse:
        order = get_object_or_404(Order, pk=pk)
        new_status = request.POST.get("new_status", "").strip()
        allowed = allowed_statuses_for_user(request.user, order)
        if new_status not in allowed:
            raise PermissionDenied("Seu perfil não permite esta transição de status.")

        reason = request.POST.get("reason", "").strip()[:255]
        idempotency_key = f"gui:{order.pk}:{order.status}:{new_status}"
        try:
            change_order_status(
                order_id=order.pk,
                new_status=new_status,
                actor=request.user,
                reason=reason,
                idempotency_key=idempotency_key,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, f"Pedido atualizado para {Order.Status(new_status).label}.")
        return redirect(reverse("order-detail", kwargs={"pk": order.pk}))


class ClosingListView(SecurePermissionMixin, ListView):
    permission_required = "orders.view_monthlyclosing"
    model = MonthlyClosing
    template_name = "orders/closing_list.html"
    context_object_name = "closings"
    paginate_by = 30

    def get_queryset(self):
        return super().get_queryset().select_related("company", "generated_by")


class AuditListView(SecurePermissionMixin, ListView):
    permission_required = "orders.view_auditevent"
    model = AuditEvent
    template_name = "orders/audit_list.html"
    context_object_name = "events"
    paginate_by = 50

    def get_queryset(self):
        return super().get_queryset().select_related("actor")
