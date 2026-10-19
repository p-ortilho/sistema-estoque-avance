from django.db import models
from django.db.models import Sum, F, DecimalField
from stock.models.Produto import Produto
from stock.models.Filial import Filial


class Estoque(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name="estoques", verbose_name="Produto")
    filial = models.ForeignKey(Filial, on_delete=models.PROTECT, related_name="estoques", verbose_name="Filial")
    quantidade_minima = models.PositiveIntegerField(default=5, verbose_name="Quantidade Mínima (alerta)")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["produto", "filial"], name="estoque_unico_por_filial")
        ]
        ordering = ["produto__nome"]

    def __str__(self):
        return f"{self.produto.nome} - {self.filial.nome}"

    @property
    def quantidade(self):
        return self.lotes.aggregate(total=Sum("quantidade_atual"))["total"] or 0

    @property
    def valor_total(self):
        total = self.lotes.aggregate(
            total=Sum(F("quantidade_atual") * F("preco_unitario"), output_field=DecimalField())
        )["total"]
        return total or 0

    @property
    def estoque_baixo(self):
        return self.quantidade <= self.quantidade_minima