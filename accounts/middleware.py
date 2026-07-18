from __future__ import annotations

from django.conf import settings
from django.shortcuts import redirect
from django.urls import Resolver404, resolve


class ForcePasswordChangeMiddleware:
    allowed_url_names = {
        "healthcheck",
        "login",
        "logout",
        "password_change",
        "password_change_done",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.must_change_password:
            if request.path.startswith(settings.STATIC_URL):
                return self.get_response(request)
            try:
                match = resolve(request.path_info)
            except Resolver404:
                match = None
            if not match or match.url_name not in self.allowed_url_names:
                return redirect("password_change")
        return self.get_response(request)
