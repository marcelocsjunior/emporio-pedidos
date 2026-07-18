from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    display_name = models.CharField("nome de exibição", max_length=150, blank=True)
    must_change_password = models.BooleanField("deve trocar a senha", default=False)

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self) -> str:
        return self.display_name or self.get_full_name() or self.username
