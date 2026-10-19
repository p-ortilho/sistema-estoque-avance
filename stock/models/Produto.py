from django.db import models

class Produto(models.Model):
    CATEGORIA_CHOICES = [
        ("filtro", "Filtro"),
        ("oleo", "Óleo"),
        ("pecas", "Peças"),
        ("outro", "Outro"),
    ]

    nome = models.CharField(max_length=200, verbose_name="Nome")
    codigo = models.CharField(max_length=50, unique=True, verbose_name="Código")
    categoria = models.CharField(
        max_length=30,
        choices=CATEGORIA_CHOICES,
        verbose_name="Categoria"
    )
    descricao = models.TextField(blank=True, null=True, verbose_name="Descrição")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")

    def __str__(self):
        return f"{self.codigo} - {self.nome}"