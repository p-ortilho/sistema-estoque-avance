from django.db import models

class Equipamento(models.Model):
    TIPO_CHOICES = [
        ("motoniveladora", "Motoniveladora"),
        ("trator", "Trator"),
        ("vibroacabadora", "Vibroacabadora"),
        ("outro", "Outro"),
    ]

    STATUS_CHOICES = [
        ("ativo", "Ativo"),
        ("inativo", "Inativo"),
    ]

    nome = models.CharField(max_length=150, verbose_name="Nome")
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, verbose_name="Tipo")
    numero_serie = models.CharField(max_length=100, unique=True, verbose_name="Número de Série")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ativo", verbose_name="Status")

    def __str__(self):
        return f"{self.nome} ({self.numero_serie})"