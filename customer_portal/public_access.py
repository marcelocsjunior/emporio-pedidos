from django.conf import settings
from django.shortcuts import render

from .access_views import PublicAccessRequestView

DISABLED_MESSAGE = (
    "A criação de acesso é realizada exclusivamente pela equipe responsável do Empório. "
    "Entre em contato com o responsável interno para solicitar seu usuário."
)

_public_access_request_view = PublicAccessRequestView.as_view()


def public_access_request_gate(request, *args, **kwargs):
    if settings.PUBLIC_ACCESS_REQUEST_ENABLED:
        return _public_access_request_view(request, *args, **kwargs)

    return render(
        request,
        "customer_portal/access_request_public.html",
        {
            "public_access_disabled": True,
            "public_message": DISABLED_MESSAGE,
        },
        status=403 if request.method == "POST" else 200,
    )
