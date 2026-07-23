from django.conf import settings


def public_access_settings(request):
    return {
        "public_access_request_enabled": settings.PUBLIC_ACCESS_REQUEST_ENABLED,
    }
