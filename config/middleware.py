from __future__ import annotations

import logging
import uuid

logger = logging.getLogger("emporio.requests")


class RequestIdMiddleware:
    """Correlaciona cada resposta e registra exceções sem expor dados sensíveis."""

    header_name = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.headers.get(self.header_name) or uuid.uuid4().hex
        response = self.get_response(request)
        response[self.header_name] = request.request_id

        if response.status_code >= 500:
            logger.error(
                "request_failed request_id=%s method=%s path=%s status=%s",
                request.request_id,
                request.method,
                request.path,
                response.status_code,
            )
        return response

    def process_exception(self, request, exception):
        logger.exception(
            "unhandled_request_error request_id=%s method=%s path=%s exception=%s",
            getattr(request, "request_id", "unavailable"),
            request.method,
            request.path,
            type(exception).__name__,
        )
        return None
