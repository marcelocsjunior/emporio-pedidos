from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.db import transaction

from orders.services import record_audit

from .access import ROOT_USERNAME, is_root_system_admin
from .models import User


def root_only_admin_permission(request):
    return is_root_system_admin(request.user) and request.user.is_staff


# Mantém o site padrão (e todos os registros existentes), restringindo seu gate.
admin.site.has_permission = root_only_admin_permission


@admin.register(User)
class EmporioUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Empório", {"fields": ("display_name", "must_change_password")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Empório", {"fields": ("display_name", "must_change_password")}),
    )
    actions = ()

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        protected = ("is_staff", "is_superuser")
        if obj and obj.username == ROOT_USERNAME:
            protected += ("username", "is_active", "groups", "user_permissions")
        return (*super().get_readonly_fields(request, obj), *protected)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST" and object_id:
            target = User.objects.filter(pk=object_id).first()
            if target and target.username == ROOT_USERNAME:
                protected = {
                    "username",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                }
                if protected.intersection(request.POST):
                    record_audit(
                        actor=request.user,
                        action="root_admin.change_denied",
                        entity=target,
                        payload={"denied": True, "reason": "admin_protected_fields"},
                    )
        return super().changeform_view(request, object_id, form_url, extra_context)

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if obj.username == ROOT_USERNAME:
            if change:
                original = User.objects.select_for_update().get(pk=obj.pk)
                obj.username = ROOT_USERNAME
                obj.is_active = True
                obj.is_staff = True
                obj.is_superuser = True
                if original.username != ROOT_USERNAME:
                    raise PermissionDenied("A conta raiz não pode ser renomeada.")
            else:
                raise PermissionDenied(
                    "A conta raiz deve existir previamente e não pode ser criada pelo Admin."
                )
        else:
            obj.is_staff = False
            obj.is_superuser = False
        super().save_model(request, obj, form, change)
