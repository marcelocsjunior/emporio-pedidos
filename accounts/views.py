from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView, PasswordChangeDoneView, PasswordChangeView
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import ListView, TemplateView

from orders.services import record_audit

from .access import Capability, CapabilityRequiredMixin, user_has_capability
from .forms import AttendantCreateForm, AttendantUpdateForm
from .roles import ROLE_ATTENDANCE

User = get_user_model()


class EmporioLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_success_url(self) -> str:
        user = self.request.user
        if user_has_capability(user, Capability.VIEW_ORDERS):
            return reverse("dashboard")
        if user_has_capability(user, Capability.ACCESS_TECHNICAL_AREA):
            return reverse("technical-area")
        try:
            access = user.customer_portal_access
        except ObjectDoesNotExist:
            return super().get_success_url()
        if access.active and access.company.active:
            return reverse("customer_portal:request-list")
        return super().get_success_url()


class EmporioPasswordChangeView(PasswordChangeView):
    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("password_change_done")

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.user.must_change_password:
            self.request.user.must_change_password = False
            self.request.user.save(update_fields=("must_change_password",))
        messages.success(self.request, "Senha atualizada com segurança.")
        return response


class EmporioPasswordChangeDoneView(PasswordChangeDoneView):
    template_name = "registration/password_change_done.html"


class AttendantListView(CapabilityRequiredMixin, ListView):
    capability_required = Capability.MANAGE_ATTENDANTS
    template_name = "accounts/attendant_list.html"
    context_object_name = "attendants"

    def get_queryset(self):
        return User.objects.filter(groups__name=ROLE_ATTENDANCE).order_by("username")


class AttendantCreateView(CapabilityRequiredMixin, View):
    capability_required = Capability.MANAGE_ATTENDANTS
    template_name = "accounts/attendant_form.html"

    def get(self, request):
        return self._render(request, AttendantCreateForm(), True)

    @transaction.atomic
    def post(self, request):
        form = AttendantCreateForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, True)
        user = form.save()
        user.groups.add(get_object_or_404(Group, name=ROLE_ATTENDANCE))
        record_audit(
            actor=request.user,
            action="attendant.created",
            entity=user,
            payload={"username": user.username, "active": user.is_active},
        )
        messages.success(request, "Atendente criado com troca obrigatória de senha.")
        return redirect("attendant-list")

    def _render(self, request, form, creating):
        return render(request, self.template_name, {"form": form, "creating": creating})


class AttendantUpdateView(CapabilityRequiredMixin, View):
    capability_required = Capability.MANAGE_ATTENDANTS
    template_name = "accounts/attendant_form.html"

    def get_object(self, pk):
        return get_object_or_404(User, pk=pk, groups__name=ROLE_ATTENDANCE)

    def get(self, request, pk):
        user = self.get_object(pk)
        return render(
            request,
            self.template_name,
            {
                "form": AttendantUpdateForm(instance=user),
                "attendant": user,
                "creating": False,
            },
        )

    @transaction.atomic
    def post(self, request, pk):
        user = self.get_object(pk)
        before = {"username": user.username, "display_name": user.display_name}
        form = AttendantUpdateForm(request.POST, instance=user)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "attendant": user, "creating": False},
            )
        user = form.save()
        record_audit(
            actor=request.user,
            action="attendant.updated",
            entity=user,
            payload={
                "before": before,
                "after": {"username": user.username, "display_name": user.display_name},
            },
        )
        messages.success(request, "Cadastro do Atendente atualizado.")
        return redirect("attendant-list")


class AttendantToggleActiveView(CapabilityRequiredMixin, View):
    capability_required = Capability.MANAGE_ATTENDANTS
    http_method_names = ("post",)

    @transaction.atomic
    def post(self, request, pk):
        user = get_object_or_404(
            User.objects.select_for_update(), pk=pk, groups__name=ROLE_ATTENDANCE
        )
        user.is_active = not user.is_active
        user.save(update_fields=("is_active",))
        record_audit(
            actor=request.user,
            action="attendant.reactivated" if user.is_active else "attendant.suspended",
            entity=user,
            payload={"active": user.is_active},
        )
        messages.success(request, "Acesso reativado." if user.is_active else "Acesso suspenso.")
        return redirect("attendant-list")


class AttendantRequirePasswordChangeView(CapabilityRequiredMixin, View):
    capability_required = Capability.MANAGE_ATTENDANTS
    http_method_names = ("post",)

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk, groups__name=ROLE_ATTENDANCE)
        user.must_change_password = True
        user.save(update_fields=("must_change_password",))
        record_audit(
            actor=request.user,
            action="attendant.password_change_required",
            entity=user,
        )
        messages.success(request, "Troca de senha obrigatória ativada para o próximo acesso.")
        return redirect("attendant-list")


class TechnicalAreaView(CapabilityRequiredMixin, TemplateView):
    capability_required = Capability.ACCESS_TECHNICAL_AREA
    template_name = "accounts/technical_area.html"
