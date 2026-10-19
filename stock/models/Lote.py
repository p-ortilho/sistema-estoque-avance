from django.db import models
from stock.models.Estoque import Estoque


class Lote(models.Model):
    estoque = models.ForeignKey(Estoque, on_delete=models.PROTECT, related_name="lotes", verbose_name="Estoque")
    fornecedor = models.CharField(max_length=100, blank=True, verbose_name="Fornecedor")
    nf = models.CharField(max_length=10, blank=True, verbose_name="NF")
    chave = models.CharField(max_length=44, blank=True, verbose_name="Chave de acesso")
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço Unitário")
    quantidade_entrada = models.PositiveIntegerField(verbose_name="Quantidade de entrada")
    quantidade_atual = models.PositiveIntegerField(verbose_name="Saldo do lote", default=0, editable=False)
    data_entrada = models.DateField(verbose_name="Data de entrada")

    class Meta:
        ordering = ["data_entrada", "id"]  # mais antigo primeiro (útil para baixa PEPS)

    def __str__(self):
        return (f"{self.estoque} | NF {self.nf or '-'} | {self.estoque.produto.codigo} | "f"{self.data_entrada:%d/%m/%Y}"
    )

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.quantidade_atual = self.quantidade_entrada
        super().save(*args, **kwargs)