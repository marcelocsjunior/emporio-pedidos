from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView, PasswordChangeDoneView, PasswordChangeView
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import ListView, TemplateView

from orders.services import record_audit

from .access import (
    ROOT_USERNAME,
    Capability,
    CapabilityRequiredMixin,
    is_root_system_admin,
    user_has_capability,
)
from .forms import AttendantCreateForm, AttendantUpdateForm, ManagedUserForm
from .roles import ROLE_ATTENDANCE, ROLE_SYSTEM_ADMIN
from .user_management import (
    MANAGED_ROLE_NAMES,
    assert_can_manage,
    audit_denied,
    can_manage_user,
    display_role,
    require_password_change,
    roles_actor_can_assign,
    toggle_user_active,
    user_role,
)

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


class UserAccessListView(CapabilityRequiredMixin, ListView):
    capability_required = Capability.MANAGE_ATTENDANTS
    template_name = "accounts/user_list.html"
    context_object_name = "managed_users"

    def get_queryset(self):
        actor = self.request.user
        if user_has_capability(actor, Capability.VIEW_ALL_USERS):
            queryset = User.objects.filter(
                Q(username=ROOT_USERNAME) | Q(groups__name__in=MANAGED_ROLE_NAMES)
            ).distinct()
        else:
            queryset = User.objects.filter(groups__name=ROLE_ATTENDANCE)
        users = list(queryset.prefetch_related("groups").order_by("username"))
        for user in users:
            user.visible_role = display_role(user)
            user.can_be_managed = can_manage_user(actor, user) or (
                user.pk == actor.pk and is_root_system_admin(actor)
            )
            user.is_protected_root = user.username == ROOT_USERNAME
        return users

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_create_users"] = bool(roles_actor_can_assign(self.request.user))
        return context


class UserAccessCreateView(CapabilityRequiredMixin, View):
    capability_required = Capability.MANAGE_ATTENDANTS
    template_name = "accounts/user_form.html"

    def get(self, request):
        return self._render(request, ManagedUserForm(actor=request.user), True)

    @transaction.atomic
    def post(self, request):
        form = ManagedUserForm(request.POST, actor=request.user)
        if not form.is_valid():
            if {"is_staff", "is_superuser", "groups", "user_permissions"}.intersection(
                request.POST
            ):
                audit_denied(
                    actor=request.user,
                    target=request.user,
                    action="user.privilege_escalation_denied",
                    reason="protected_post_fields",
                )
            return self._render(request, form, True)
        if form.cleaned_data["role"] not in roles_actor_can_assign(request.user):
            raise PermissionDenied("Perfil fora do escopo autorizado.")
        user = form.save()
        action = (
            "system_admin.created"
            if user_role(user) == ROLE_SYSTEM_ADMIN
            else "user.created"
        )
        record_audit(
            actor=request.user,
            action=action,
            entity=user,
            payload={"username": user.username, "role": display_role(user), "active": True},
        )
        messages.success(request, "Usuário criado com troca obrigatória de senha.")
        return redirect("user-access-list")

    def _render(self, request, form, creating):
        return render(request, self.template_name, {"form": form, "creating": creating})


class UserAccessUpdateView(CapabilityRequiredMixin, View):
    capability_required = Capability.MANAGE_ATTENDANTS
    template_name = "accounts/user_form.html"

    def _get_target(self, pk):
        return get_object_or_404(User.objects.prefetch_related("groups"), pk=pk)

    def _authorize(self, actor, target):
        if (
            target.username == ROOT_USERNAME
            and actor.pk == target.pk
            and is_root_system_admin(actor)
        ):
            return
        assert_can_manage(actor, target)

    def get(self, request, pk):
        target = self._get_target(pk)
        self._authorize(request.user, target)
        return self._render(
            request,
            ManagedUserForm(instance=target, actor=request.user),
            target,
        )

    @transaction.atomic
    def post(self, request, pk):
        target = get_object_or_404(User.objects.select_for_update(), pk=pk)
        self._authorize(request.user, target)
        before = {
            "username": target.username,
            "display_name": target.display_name,
            "role": display_role(target),
        }
        form = ManagedUserForm(request.POST, instance=target, actor=request.user)
        if not form.is_valid():
            if target.username == ROOT_USERNAME:
                audit_denied(
                    actor=request.user,
                    target=target,
                    action="root_admin.change_denied",
                    reason="protected_fields",
                )
            return self._render(request, form, target)
        # Revalidação feita com a linha bloqueada imediatamente antes da gravação.
        self._authorize(request.user, target)
        user = form.save()
        after_role = display_role(user)
        if user_role(user) == ROLE_SYSTEM_ADMIN:
            action = "system_admin.updated"
        elif before["role"] != after_role:
            action = "user.role_changed"
        else:
            action = "user.updated"
        record_audit(
            actor=request.user,
            action=action,
            entity=user,
            payload={
                "before": before,
                "after": {
                    "username": user.username,
                    "display_name": user.display_name,
                    "role": after_role,
                },
            },
        )
        messages.success(request, "Cadastro atualizado.")
        return redirect("user-access-list")

    def _render(self, request, form, target):
        return render(
            request,
            self.template_name,
            {"form": form, "managed_user": target, "creating": False},
        )


class UserAccessToggleActiveView(CapabilityRequiredMixin, View):
    capability_required = Capability.MANAGE_ATTENDANTS
    http_method_names = ("post",)

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        toggle_user_active(actor=request.user, target=target)
        messages.success(request, "Situação de acesso atualizada.")
        return redirect("user-access-list")


class UserAccessRequirePasswordChangeView(CapabilityRequiredMixin, View):
    capability_required = Capability.MANAGE_ATTENDANTS
    http_method_names = ("post",)

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        require_password_change(actor=request.user, target=target)
        messages.success(request, "Troca de senha exigida para o próximo acesso.")
        return redirect("user-access-list")


class TechnicalAreaView(CapabilityRequiredMixin, TemplateView):
    capability_required = Capability.ACCESS_TECHNICAL_AREA
    template_name = "accounts/technical_area.html"
