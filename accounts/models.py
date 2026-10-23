from django.db import models
from django.conf import settings
from stock.models import Filial


class Perfil(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil",
        verbose_name="Usuário"
    )
    filiais = models.ManyToManyField(
        Filial,
        related_name="perfis",
        verbose_name="Filiais",
        blank=True
    )
    cargo = models.CharField(max_length=100, blank=True, null=True, verbose_name="Cargo")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    def __str__(self):
        filiais_str = ", ".join([f.nome for f in self.filiais.all()])
        return f"{self.usuario.get_full_name() or self.usuario.username} - [{filiais_str}]"