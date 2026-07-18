from django.core.management.base import BaseCommand

from accounts.roles import ensure_roles


class Command(BaseCommand):
    help = "Cria ou sincroniza os perfis internos e suas permissões."

    def handle(self, *args, **options):
        groups = ensure_roles(strict=True)
        summary = ", ".join(
            f"{name} ({group.permissions.count()} permissões)"
            for name, group in groups.items()
        )
        self.stdout.write(self.style.SUCCESS(f"Perfis sincronizados: {summary}"))
