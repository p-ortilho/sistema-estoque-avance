from django.db import models

class Filial(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    codigo = models.IntegerField(unique=True, verbose_name="Código da Filial")
    ativa = models.BooleanField(default=True, verbose_name="Ativa")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    def __str__(self):
        return f"{self.codigo} - {self.nome}"