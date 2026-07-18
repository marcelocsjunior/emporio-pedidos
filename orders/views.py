from __future__ import annotations

import uuid
from datetime import date

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from .access import allowed_statuses_for_user
from .forms import CompanyForm, OrderCreateForm, OrderForm, OrderItemFormSet, ProductForm
from .models import AuditEvent, Company, MonthlyClosing, Order, Product
from .services import (
    ORDER_EDITABLE_STATUSES,
    change_order_status,
    create_order_from_forms,
    record_audit,
    update_order_from_forms,
)


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


class CompanyCreateView(SecurePermissionMixin, View):
    permission_required = "orders.add_company"
    template_name = "orders/company_form.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, self.template_name, {"form": CompanyForm(), "creating": True})

    def post(self, request: HttpRequest) -> HttpResponse:
        form = CompanyForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "creating": True})
        with transaction.atomic():
            company = form.save()
            record_audit(
                actor=request.user,
                action="company.created",
                entity=company,
                payload={"code": company.code, "name": company.name, "active": company.active},
            )
        messages.success(request, "Empresa cadastrada com sucesso.")
        return redirect("company-list")


class CompanyUpdateView(SecurePermissionMixin, View):
    permission_required = "orders.change_company"
    template_name = "orders/company_form.html"

    def get_object(self, pk) -> Company:
        return get_object_or_404(Company, pk=pk)

    def get(self, request: HttpRequest, pk) -> HttpResponse:
        company = self.get_object(pk)
        return render(
            request,
            self.template_name,
            {"form": CompanyForm(instance=company), "company": company, "creating": False},
        )

    def post(self, request: HttpRequest, pk) -> HttpResponse:
        company = self.get_object(pk)
        before = {"name": company.name, "active": company.active}
        form = CompanyForm(request.POST, instance=company)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "company": company, "creating": False},
            )
        with transaction.atomic():
            company = form.save()
            record_audit(
                actor=request.user,
                action="company.updated",
                entity=company,
                payload={
                    "before": before,
                    "after": {"name": company.name, "active": company.active},
                },
            )
        messages.success(request, "Empresa atualizada com sucesso.")
        return redirect("company-list")


class CompanyToggleActiveView(SecurePermissionMixin, View):
    permission_required = "orders.change_company"
    http_method_names = ("post",)

    @transaction.atomic
    def post(self, request: HttpRequest, pk) -> HttpResponse:
        company = get_object_or_404(Company.objects.select_for_update(), pk=pk)
        previous = company.active
        company.active = not company.active
        company.save(update_fields=("active", "updated_at"))
        record_audit(
            actor=request.user,
            action="company.activated" if company.active else "company.deactivated",
            entity=company,
            payload={"from": previous, "to": company.active},
        )
        messages.success(
            request,
            "Empresa ativada." if company.active else "Empresa inativada para novos pedidos.",
        )
        return redirect("company-list")


class ProductListView(SecurePermissionMixin, SearchableListMixin, ListView):
    permission_required = "orders.view_product"
    model = Product
    template_name = "orders/product_list.html"
    context_object_name = "products"
    paginate_by = 30
    search_fields = ("code", "name", "category")


class ProductCreateView(SecurePermissionMixin, View):
    permission_required = "orders.add_product"
    template_name = "orders/product_form.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, self.template_name, {"form": ProductForm(), "creating": True})

    def post(self, request: HttpRequest) -> HttpResponse:
        form = ProductForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "creating": True})
        with transaction.atomic():
            product = form.save()
            record_audit(
                actor=request.user,
                action="product.created",
                entity=product,
                payload={
                    "code": product.code,
                    "name": product.name,
                    "unit_price": str(product.unit_price),
                    "active": product.active,
                },
            )
        messages.success(request, "Produto cadastrado com sucesso.")
        return redirect("product-list")


class ProductUpdateView(SecurePermissionMixin, View):
    permission_required = "orders.change_product"
    template_name = "orders/product_form.html"

    def get_object(self, pk) -> Product:
        return get_object_or_404(Product, pk=pk)

    def get(self, request: HttpRequest, pk) -> HttpResponse:
        product = self.get_object(pk)
        return render(
            request,
            self.template_name,
            {"form": ProductForm(instance=product), "product": product, "creating": False},
        )

    def post(self, request: HttpRequest, pk) -> HttpResponse:
        product = self.get_object(pk)
        before = {
            "name": product.name,
            "unit_price": str(product.unit_price),
            "active": product.active,
        }
        form = ProductForm(request.POST, instance=product)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "product": product, "creating": False},
            )
        with transaction.atomic():
            product = form.save()
            record_audit(
                actor=request.user,
                action="product.updated",
                entity=product,
                payload={
                    "before": before,
                    "after": {
                        "name": product.name,
                        "unit_price": str(product.unit_price),
                        "active": product.active,
                    },
                },
            )
        messages.success(
            request,
            "Produto atualizado. Pedidos anteriores mantêm o preço congelado.",
        )
        return redirect("product-list")


class ProductToggleActiveView(SecurePermissionMixin, View):
    permission_required = "orders.change_product"
    http_method_names = ("post",)

    @transaction.atomic
    def post(self, request: HttpRequest, pk) -> HttpResponse:
        product = get_object_or_404(Product.objects.select_for_update(), pk=pk)
        previous = product.active
        product.active = not product.active
        product.save(update_fields=("active", "updated_at"))
        record_audit(
            actor=request.user,
            action="product.activated" if product.active else "product.deactivated",
            entity=product,
            payload={"from": previous, "to": product.active},
        )
        messages.success(
            request,
            "Produto ativado." if product.active else "Produto inativado para novos pedidos.",
        )
        return redirect("product-list")


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


class OrderCreateView(SecurePermissionMixin, View):
    permission_required = ("orders.add_order", "orders.add_orderitem")
    template_name = "orders/order_form.html"
    session_key = "emporio_order_creation_key"

    def get(self, request: HttpRequest) -> HttpResponse:
        creation_key = uuid.uuid4().hex
        request.session[self.session_key] = creation_key
        draft = Order()
        form = OrderCreateForm(
            instance=draft,
            initial={
                "creation_key": creation_key,
                "order_date": timezone.localdate(),
                "delivery_date": timezone.localdate(),
            },
        )
        formset = OrderItemFormSet(instance=draft, prefix="items")
        return render(
            request,
            self.template_name,
            {"form": form, "formset": formset, "creating": True, "can_edit_items": True},
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        creation_key = request.POST.get("creation_key", "").strip()
        existing = Order.objects.filter(creation_key=creation_key).first() if creation_key else None
        if existing:
            messages.info(
                request,
                "Este pedido já havia sido salvo; nenhuma duplicidade foi criada.",
            )
            return redirect("order-detail", pk=existing.pk)

        draft = Order()
        form = OrderCreateForm(request.POST, instance=draft)
        formset = OrderItemFormSet(request.POST, instance=draft, prefix="items")
        forms_valid = form.is_valid() and formset.is_valid()
        expected_key = request.session.get(self.session_key)
        if forms_valid and creation_key != expected_key:
            form.add_error("creation_key", "A sessão do formulário expirou. Reabra o novo pedido.")
            forms_valid = False

        if forms_valid:
            order, created = create_order_from_forms(
                order_form=form,
                item_formset=formset,
                actor=request.user,
                creation_key=creation_key,
            )
            request.session.pop(self.session_key, None)
            if created:
                messages.success(request, f"Pedido {order.number} criado com sucesso.")
            else:
                messages.info(request, "Pedido já existente; repetição ignorada com segurança.")
            return redirect("order-detail", pk=order.pk)

        return render(
            request,
            self.template_name,
            {"form": form, "formset": formset, "creating": True, "can_edit_items": True},
        )


class OrderUpdateView(SecurePermissionMixin, View):
    permission_required = "orders.change_order"
    template_name = "orders/order_form.html"

    def get_object(self, pk) -> Order:
        return get_object_or_404(Order.objects.select_related("company"), pk=pk)

    def _guard(self, order: Order) -> None:
        if order.status not in ORDER_EDITABLE_STATUSES:
            raise PermissionDenied("O pedido não pode mais ser editado neste status.")

    def get(self, request: HttpRequest, pk) -> HttpResponse:
        order = self.get_object(pk)
        self._guard(order)
        can_edit_items = order.status == Order.Status.PENDING
        formset = OrderItemFormSet(instance=order, prefix="items") if can_edit_items else None
        return render(
            request,
            self.template_name,
            {
                "form": OrderForm(instance=order),
                "formset": formset,
                "order": order,
                "creating": False,
                "can_edit_items": can_edit_items,
            },
        )

    def post(self, request: HttpRequest, pk) -> HttpResponse:
        order = self.get_object(pk)
        self._guard(order)
        can_edit_items = order.status == Order.Status.PENDING
        form = OrderForm(request.POST, instance=order)
        formset = (
            OrderItemFormSet(request.POST, instance=order, prefix="items")
            if can_edit_items
            else None
        )
        valid = form.is_valid() and (formset is None or formset.is_valid())
        if valid:
            try:
                updated = update_order_from_forms(
                    order=order,
                    order_form=form,
                    item_formset=formset,
                    actor=request.user,
                )
            except ValidationError as exc:
                form.add_error(None, "; ".join(exc.messages))
            else:
                messages.success(request, f"Pedido {updated.number} atualizado com sucesso.")
                return redirect("order-detail", pk=updated.pk)

        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "order": order,
                "creating": False,
                "can_edit_items": can_edit_items,
            },
        )


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
        context["can_edit"] = self.request.user.has_perm(
            "orders.change_order"
        ) and self.object.status in ORDER_EDITABLE_STATUSES
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
