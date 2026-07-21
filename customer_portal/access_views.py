from __future__ import annotations

from datetime import datetime, time

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from accounts.access import Capability, CapabilityRequiredMixin
from orders.models import AuditEvent, Company

from .access_forms import (
    AccessRequestReviewForm,
    AccessStatusForm,
    AdminPasswordResetForm,
    PortalUserCreateForm,
    PortalUserLinkForm,
    PublicAccessRequestForm,
)
from .access_services import (
    approve_access_request,
    create_portal_user,
    create_public_request,
    link_portal_user,
    reject_access_request,
    reset_portal_password,
    secure_fingerprint,
    set_access_active,
    start_access_request_review,
)
from .models import CustomerPortalAccess, CustomerPortalAccessRequest

PUBLIC_MESSAGE = "Solicitação recebida para análise. O envio não libera acesso automaticamente."


class PublicAccessRequestView(View):
    template_name = "customer_portal/access_request_public.html"

    def get(self, request):
        return render(request, self.template_name, {"form": PublicAccessRequestForm()})

    def post(self, request):
        form = PublicAccessRequestForm(request.POST)
        if form.is_valid():
            if not form.cleaned_data["website"]:
                create_public_request(
                    cleaned_data=form.cleaned_data,
                    remote_address=request.META.get("REMOTE_ADDR", ""),
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                )
            return render(
                request, self.template_name, {"submitted": True, "public_message": PUBLIC_MESSAGE}
            )
        return render(request, self.template_name, {"form": form}, status=400)


class ManageCompaniesMixin(CapabilityRequiredMixin):
    capability_required = Capability.MANAGE_COMPANIES


class PortalAccessListView(ManageCompaniesMixin, ListView):
    model = CustomerPortalAccess
    template_name = "customer_portal/access_list.html"
    context_object_name = "accesses"

    def get_queryset(self):
        queryset = super().get_queryset().select_related("company", "user")
        company_id = self.request.GET.get("company")
        return queryset.filter(company_id=company_id) if company_id else queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["companies"] = Company.objects.order_by("name")
        context["company_id"] = self.request.GET.get("company", "")
        return context


class PortalAccessDetailView(ManageCompaniesMixin, DetailView):
    model = CustomerPortalAccess
    template_name = "customer_portal/access_detail.html"
    context_object_name = "access"

    def get_queryset(self):
        return super().get_queryset().select_related("company", "user", "created_by", "revoked_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["events"] = AuditEvent.objects.filter(
            Q(entity_type="customer_portal.customerportalaccess", entity_id=str(self.object.pk))
            | Q(
                payload__user_id=str(self.object.user_id),
                payload__company_id=str(self.object.company_id),
            )
        )[:50]
        context["related_requests"] = CustomerPortalAccessRequest.objects.filter(
            Q(company=self.object.company) | Q(email__iexact=self.object.user.email)
        )[:20]
        return context


class PortalUserCreateView(ManageCompaniesMixin, View):
    template_name = "customer_portal/access_form.html"

    def get(self, request):
        initial = {"company": request.GET.get("company")}
        return render(
            request,
            self.template_name,
            {"form": PortalUserCreateForm(initial=initial), "creating": True},
        )

    def post(self, request):
        form = PortalUserCreateForm(request.POST)
        if form.is_valid():
            access = create_portal_user(form=form, actor=request.user)
            messages.success(request, "Usuário do portal criado e vinculado.")
            return redirect("customer_portal:access-detail", pk=access.pk)
        return render(request, self.template_name, {"form": form, "creating": True}, status=400)


class PortalUserLinkView(ManageCompaniesMixin, View):
    template_name = "customer_portal/access_form.html"

    def get(self, request):
        form = PortalUserLinkForm(initial={"company": request.GET.get("company")})
        return render(request, self.template_name, {"form": form, "creating": False})

    def post(self, request):
        form = PortalUserLinkForm(request.POST)
        if form.is_valid():
            access = link_portal_user(
                user=form.cleaned_data["user"],
                company=form.cleaned_data["company"],
                active=form.cleaned_data["active"],
                actor=request.user,
            )
            messages.success(request, "Usuário existente vinculado ao cliente.")
            return redirect("customer_portal:access-detail", pk=access.pk)
        return render(request, self.template_name, {"form": form, "creating": False}, status=400)


class PortalAccessStatusView(ManageCompaniesMixin, View):
    def post(self, request, pk, action):
        access = get_object_or_404(CustomerPortalAccess, pk=pk)
        form = AccessStatusForm(request.POST)
        if form.is_valid() and action in {"activate", "revoke"}:
            if action == "revoke" and not form.cleaned_data["reason"]:
                form.add_error("reason", "Informe o motivo do bloqueio.")
            else:
                set_access_active(
                    access=access,
                    active=action == "activate",
                    actor=request.user,
                    reason=form.cleaned_data["reason"],
                )
                messages.success(request, "Acesso atualizado.")
                return redirect("customer_portal:access-detail", pk=access.pk)
        messages.error(request, "Confirme a ação e informe os dados obrigatórios.")
        return redirect("customer_portal:access-detail", pk=access.pk)


class PortalPasswordResetView(ManageCompaniesMixin, View):
    template_name = "customer_portal/password_reset.html"

    def get(self, request, pk):
        access = get_object_or_404(
            CustomerPortalAccess.objects.select_related("user", "company"), pk=pk
        )
        return render(
            request,
            self.template_name,
            {"access": access, "form": AdminPasswordResetForm(user=access.user)},
        )

    def post(self, request, pk):
        access = get_object_or_404(
            CustomerPortalAccess.objects.select_related("user", "company"), pk=pk
        )
        form = AdminPasswordResetForm(request.POST, user=access.user)
        if form.is_valid():
            reset_portal_password(
                access=access, password=form.cleaned_data["password1"], actor=request.user
            )
            messages.success(request, "Senha redefinida. A troca será exigida no próximo acesso.")
            return redirect("customer_portal:access-detail", pk=access.pk)
        return render(request, self.template_name, {"access": access, "form": form}, status=400)


class AccessRequestQueueView(ManageCompaniesMixin, ListView):
    model = CustomerPortalAccessRequest
    template_name = "customer_portal/access_request_queue.html"
    context_object_name = "access_requests"

    def get_queryset(self):
        queryset = super().get_queryset().select_related("company", "reviewed_by")
        status = self.request.GET.get("status")
        company = self.request.GET.get("company")
        if status:
            queryset = queryset.filter(status=status)
        if company:
            queryset = queryset.filter(company_id=company)
        for field, lookup in (("from", "gte"), ("to", "lte")):
            value = self.request.GET.get(field)
            if value:
                try:
                    day = datetime.strptime(value, "%Y-%m-%d").date()
                except ValueError:
                    continue
                boundary = timezone.make_aware(
                    datetime.combine(day, time.max if field == "to" else time.min)
                )
                queryset = queryset.filter(**{f"requested_at__{lookup}": boundary})
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["statuses"] = CustomerPortalAccessRequest.Status.choices
        context["companies"] = Company.objects.order_by("name")
        matches = {
            secure_fingerprint(company.document, purpose="document"): company
            for company in Company.objects.exclude(document="").only("id", "name", "document")
        }
        for access_request in context["access_requests"]:
            access_request.possible_company = matches.get(access_request.document_fingerprint)
        return context


class AccessRequestReviewView(ManageCompaniesMixin, DetailView):
    model = CustomerPortalAccessRequest
    template_name = "customer_portal/access_request_review.html"
    context_object_name = "access_request"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = kwargs.get("form") or AccessRequestReviewForm(
            initial={"company": self.object.company}
        )
        return context

    def post(self, request, pk):
        access_request = self.get_object()
        form = AccessRequestReviewForm(request.POST)
        action = request.POST.get("action")
        if form.is_valid():
            try:
                if action == "start":
                    start_access_request_review(
                        access_request=access_request,
                        actor=request.user,
                        company=form.cleaned_data["company"],
                    )
                elif action == "approve":
                    approve_access_request(
                        access_request=access_request,
                        company=form.cleaned_data["company"],
                        user=form.cleaned_data["user"],
                        actor=request.user,
                        confirmed=form.cleaned_data["confirm"],
                    )
                elif action == "reject":
                    if not form.cleaned_data["confirm"] or not form.cleaned_data["decision_notes"]:
                        raise ValueError("A rejeição exige confirmação e justificativa interna.")
                    reject_access_request(
                        access_request=access_request,
                        reason=form.cleaned_data["decision_notes"],
                        actor=request.user,
                    )
                else:
                    raise ValueError("Ação inválida.")
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, "Solicitação atualizada.")
                return redirect("customer_portal:access-request-review", pk=pk)
        self.object = access_request
        return self.render_to_response(self.get_context_data(form=form), status=400)
