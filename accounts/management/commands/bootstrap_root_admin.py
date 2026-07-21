from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.access import ROOT_USERNAME
from orders.services import record_audit


class Command(BaseCommand):
    help = "Promove de forma explícita e idempotente a conta raiz existente."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        username = options["username"]
        if username != ROOT_USERNAME:
            raise CommandError(f"Somente o username {ROOT_USERNAME!r} é aceito.")

        User = get_user_model()
        try:
            user = User.objects.select_for_update().get(username=ROOT_USERNAME)
        except User.DoesNotExist as exc:
            raise CommandError("A conta raiz não existe; nenhum usuário foi criado.") from exc

        before = {
            "is_active": user.is_active,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
        }
        after = {"is_active": True, "is_staff": True, "is_superuser": True}
        self.stdout.write(f"Estado anterior: {before}")
        self.stdout.write(f"Estado final: {after}")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run: nenhuma alteração realizada."))
            return

        changed_fields = [field for field, value in after.items() if getattr(user, field) != value]
        for field, value in after.items():
            setattr(user, field, value)
        if changed_fields:
            user.save(update_fields=changed_fields)
            record_audit(
                actor=user,
                action="root_admin.promoted",
                entity=user,
                payload={"before": before, "after": after},
            )
        self.stdout.write(self.style.SUCCESS("Conta raiz verificada com sucesso."))
