from django.contrib import admin

from .models import (
    AuditEvent,
    Company,
    MonthlyClosing,
    Order,
    OrderItem,
    OrderStatusHistory,
    Product,
)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "responsible_name", "customer_type", "active")
    list_filter = ("customer_type", "active", "city")
    search_fields = ("code", "name", "responsible_name", "phone")
    readonly_fields = ("code", "created_at", "updated_at")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "unit_price", "active")
    list_filter = ("active", "category")
    search_fields = ("code", "name", "category")
    readonly_fields = ("code", "created_at", "updated_at")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product_name", "line_total", "created_at", "updated_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "company",
        "delivery_date",
        "delivery_time",
        "status",
        "total_amount",
    )
    list_filter = ("status", "delivery_date", "company")
    search_fields = ("number", "company__name", "delivery_location", "notes")
    readonly_fields = (
        "number",
        "total_amount",
        "delivered_at",
        "cancelled_at",
        "created_at",
        "updated_at",
    )
    inlines = (OrderItemInline,)


@admin.register(MonthlyClosing)
class MonthlyClosingAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "reference_month",
        "order_count",
        "item_count",
        "total_amount",
        "status",
    )
    list_filter = ("status", "reference_month", "company")
    search_fields = ("company__name", "message_snapshot")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("order", "from_status", "to_status", "changed_by", "changed_at")
    list_filter = ("from_status", "to_status", "changed_at")
    search_fields = ("order__number", "reason", "idempotency_key")
    readonly_fields = tuple(field.name for field in OrderStatusHistory._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "entity_type", "entity_id", "actor", "created_at")
    list_filter = ("action", "entity_type", "created_at")
    search_fields = ("entity_id", "action")
    readonly_fields = tuple(field.name for field in AuditEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
