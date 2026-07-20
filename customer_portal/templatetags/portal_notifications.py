from django import template

from customer_portal.models import CustomerPortalAccess
from customer_portal.order_notifications import build_order_status_notification_panel

register = template.Library()


@register.inclusion_tag("customer_portal/_order_notifications.html")
def portal_order_notifications(user):
    if not user.is_authenticated:
        return {"order_notification_panel": None}
    access = CustomerPortalAccess.objects.filter(
        user=user,
        active=True,
        company__active=True,
    ).select_related("company").first()
    if access is None:
        return {"order_notification_panel": None}
    return {
        "order_notification_panel": build_order_status_notification_panel(
            user,
            access.company,
        )
    }
