from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self) -> None:
        from django.db.models.signals import post_migrate

        from .roles import bootstrap_roles_after_migrate

        post_migrate.connect(
            bootstrap_roles_after_migrate,
            dispatch_uid="accounts.bootstrap_roles_after_migrate",
            weak=False,
        )
