from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class EmporioUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Empório", {"fields": ("display_name", "must_change_password")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Empório", {"fields": ("display_name", "must_change_password")}),
    )
