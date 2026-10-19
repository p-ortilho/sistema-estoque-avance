from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F

from stock.models.Equipamento import Equipamento
from stock.models.Lote import Lote
from stock.models.Produto import Produto


class AplicacaoEstoque(models.Model):
    equipamento = models.ForeignKey(
        Equipamento,
        on_delete=models.PROTECT,
        related_name="aplicacoes",
        verbose_name="Equipamento",
    )
    lote = models.ForeignKey(
        Lote,
        on_delete=models.PROTECT,  # um lote com aplicações não pode ser excluído
        related_name="aplicacoes",
        verbose_name="Lote",
    )
    # Preenchido automaticamente a partir do lote escolhido
    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
        related_name="aplicacoes",
        editable=False,
        verbose_name="Produto",
    )
    quantidade = models.PositiveIntegerField(verbose_name="Quantidade Aplicada")
    # Cópia do preço do lote no momento da aplicação
    preco_unitario_aplicado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        verbose_name="Preço unitário aplicado",
    )
    aplicado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="aplicacoes_realizadas",
        verbose_name="Aplicado por",
    )
    data_aplicacao = models.DateTimeField(auto_now_add=True, verbose_name="Data da Aplicação")
    observacao = models.TextField(blank=True, verbose_name="Observação")

    class Meta:
        ordering = ["-data_aplicacao"]
        verbose_name = "Aplicação de estoque"
        verbose_name_plural = "Aplicações de estoque"

    def __str__(self):
        return f"{self.produto.nome} → {self.equipamento.nome} ({self.quantidade} un.)"

    @property
    def valor_total(self):
        return self.quantidade * self.preco_unitario_aplicado

    # ------------------------------------------------------------------
    # Validação (roda no formulário do admin, antes de salvar)
    # ------------------------------------------------------------------
    def _quantidade_ja_tirada_deste_lote(self):
        """Na edição, quanto esta aplicação já tinha tirado do MESMO lote."""
        if self._state.adding:
            return 0
        anterior = (
            AplicacaoEstoque.objects.filter(pk=self.pk)
            .values("lote_id", "quantidade")
            .first()
        )
        if anterior and anterior["lote_id"] == self.lote_id:
            return anterior["quantidade"]
        return 0

    def clean(self):
        super().clean()

        if self.quantidade is not None and self.quantidade < 1:
            raise ValidationError({"quantidade": "A quantidade deve ser maior que zero."})

        if not (self.lote_id and self.quantidade):
            return

        # Busca o lote direto do banco para usar o saldo atualizado
        lote = Lote.objects.get(pk=self.lote_id)

        # O lote precisa ter saldo suficiente
        disponivel = lote.quantidade_atual + self._quantidade_ja_tirada_deste_lote()
        if self.quantidade > disponivel:
            raise ValidationError({
                "quantidade": (
                    f"Saldo insuficiente no lote. Disponível: {disponivel}, "
                    f"solicitado: {self.quantidade}."
                )
            })

    # ------------------------------------------------------------------
    # Baixa no lote
    # ------------------------------------------------------------------
    def save(self, *args, **kwargs):
        with transaction.atomic():
            # 1. Edição: devolve ao lote antigo o que já tinha sido tirado
            if not self._state.adding:
                anterior = AplicacaoEstoque.objects.select_for_update().get(pk=self.pk)
                Lote.objects.filter(pk=anterior.lote_id).update(
                    quantidade_atual=F("quantidade_atual") + anterior.quantidade
                )

            # 2. Trava a linha do lote (evita duas baixas simultâneas) e confere o saldo
            lote = Lote.objects.select_for_update().get(pk=self.lote_id)
            if self.quantidade > lote.quantidade_atual:
                raise ValidationError(
                    {"quantidade": f"Saldo insuficiente no lote. Disponível: {lote.quantidade_atual}."}
                )

            # 3. Desconta do lote
            lote.quantidade_atual -= self.quantidade
            lote.save(update_fields=["quantidade_atual"])

            # 4. Copia produto e preço do lote para a aplicação
            self.lote = lote  # mantém o lote em memória com o saldo novo
            self.produto_id = lote.estoque.produto_id
            self.preco_unitario_aplicado = lote.preco_unitario

            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Excluir uma aplicação devolve a quantidade ao lote (estorno)
        with transaction.atomic():
            anterior = AplicacaoEstoque.objects.select_for_update().get(pk=self.pk)
            Lote.objects.filter(pk=anterior.lote_id).update(
                quantidade_atual=F("quantidade_atual") + anterior.quantidade
            )
            return super().delete(*args, **kwargs)