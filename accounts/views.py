from django.contrib import messages
from django.contrib.auth.views import LoginView, PasswordChangeDoneView, PasswordChangeView
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse, reverse_lazy


class EmporioLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_success_url(self) -> str:
        user = self.request.user
        if user.has_perm("orders.view_order"):
            return reverse("dashboard")
        try:
            access = user.customer_portal_access
        except ObjectDoesNotExist:
            return super().get_success_url()
        if access.active and access.company.active:
            return reverse("customer_portal:request-list")
        return super().get_success_url()


class EmporioPasswordChangeView(PasswordChangeView):
    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("password_change_done")

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.user.must_change_password:
            self.request.user.must_change_password = False
            self.request.user.save(update_fields=("must_change_password",))
        messages.success(self.request, "Senha atualizada com segurança.")
        return response


class EmporioPasswordChangeDoneView(PasswordChangeDoneView):
    template_name = "registration/password_change_done.html"
