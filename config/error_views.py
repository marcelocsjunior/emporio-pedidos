from django.shortcuts import render


def server_error(request):
    return render(
        request,
        "500.html",
        {"request_id": getattr(request, "request_id", "indisponível")},
        status=500,
    )
