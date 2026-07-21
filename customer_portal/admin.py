from django.contrib import admin

from .models import (
    CustomerDeliveryLocation,
    CustomerOrderRequest,
    CustomerOrderRequestItem,
    CustomerPortalAccess,
    CustomerPortalAccessRequest,
)


@admin.register(CustomerPortalAccess)
class CustomerPortalAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "company", "active", "updated_at")
    list_filter = ("active",)
    search_fields = ("user__username", "user__email", "company__name", "company__code")


@admin.register(CustomerPortalAccessRequest)
class CustomerPortalAccessRequestAdmin(admin.ModelAdmin):
    list_display = ("customer_name", "requester_name", "status", "requested_at", "reviewed_by")
    list_filter = ("status", "entity_type")
    search_fields = ("customer_name", "requester_name")
    readonly_fields = tuple(field.name for field in CustomerPortalAccessRequest._meta.fields)


@admin.register(CustomerDeliveryLocation)
class CustomerDeliveryLocationAdmin(admin.ModelAdmin):
    list_display = ("label", "company", "city", "active")
    list_filter = ("active", "city")
    search_fields = ("label", "address", "city", "company__name")


class CustomerOrderRequestItemInline(admin.TabularInline):
    model = CustomerOrderRequestItem
    extra = 0
    readonly_fields = ("product_name", "unit_price", "line_total")


@admin.register(CustomerOrderRequest)
class CustomerOrderRequestAdmin(admin.ModelAdmin):
    list_display = (
        "protocol",
        "company",
        "status",
        "delivery_date",
        "total_amount",
        "requested_by",
    )
    list_filter = ("status", "delivery_date", "company")
    search_fields = ("protocol", "company__name", "requested_by__username")
    readonly_fields = (
        "protocol",
        "creation_key",
        "total_amount",
        "delivery_address_snapshot",
        "submitted_at",
        "approved_at",
        "cancelled_at",
        "created_at",
        "updated_at",
    )
    inlines = (CustomerOrderRequestItemInline,)
