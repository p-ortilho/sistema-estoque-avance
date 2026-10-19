from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from stock.models.Estoque import Estoque
from stock.models.Filial import Filial
from stock.models.Lote import Lote
from stock.models.Produto import Produto


class TransferenciaEstoque(models.Model):
    STATUS_CHOICES = [
        ("pendente", "Pendente"),
        ("confirmada", "Confirmada"),
        ("cancelada", "Cancelada"),
    ]

    # Lote de onde o produto sai (define produto, filial de origem e preço)
    lote = models.ForeignKey(
        Lote,
        on_delete=models.PROTECT,
        related_name="transferencias_saida",
        verbose_name="Lote de origem",
    )
    filial_destino = models.ForeignKey(
        Filial,
        on_delete=models.PROTECT,
        related_name="transferencias_destino",
        verbose_name="Filial de Destino",
    )
    quantidade = models.PositiveIntegerField(verbose_name="Quantidade")
    observacao = models.TextField(blank=True, verbose_name="Observação")

    # --- Preenchidos automaticamente a partir do lote ---
    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
        related_name="transferencias",
        editable=False,
        verbose_name="Produto",
    )
    filial_origem = models.ForeignKey(
        Filial,
        on_delete=models.PROTECT,
        related_name="transferencias_origem",
        editable=False,
        verbose_name="Filial de Origem",
    )
    preco_unitario = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        editable=False,
        verbose_name="Preço Unitário",
    )

    # --- Controle do fluxo ---
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pendente",
        editable=False,  # muda só pelas ações Confirmar/Cancelar
        verbose_name="Status",
    )
    # Lote criado na filial de destino quando a transferência é confirmada
    lote_destino = models.OneToOneField(
        Lote,
        on_delete=models.PROTECT,
        related_name="transferencia_entrada",
        null=True,
        blank=True,
        editable=False,
        verbose_name="Lote gerado no destino",
    )
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="transferencias_solicitadas",
        verbose_name="Solicitado por",
    )
    confirmado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="transferencias_confirmadas",
        blank=True,
        null=True,
        verbose_name="Confirmado/Cancelado por",
    )
    data_solicitacao = models.DateTimeField(auto_now_add=True, verbose_name="Data da Solicitação")
    data_confirmacao = models.DateTimeField(blank=True, null=True, verbose_name="Data da Confirmação/Cancelamento")

    class Meta:
        verbose_name = "Transferência de Estoque"
        verbose_name_plural = "Transferências de Estoque"
        ordering = ["-data_solicitacao"]

    def __str__(self):
        return f"{self.produto.nome}: {self.filial_origem.nome} → {self.filial_destino.nome} ({self.quantidade} un.)"

    @property
    def valor_total(self):
        return self.quantidade * (self.preco_unitario or 0)

    # ------------------------------------------------------------------
    # Validação (formulário do admin)
    # ------------------------------------------------------------------
    def clean(self):
        super().clean()

        if self.quantidade is not None and self.quantidade < 1:
            raise ValidationError({"quantidade": "A quantidade deve ser maior que zero."})

        if not self.lote_id:
            return

        lote = Lote.objects.select_related("estoque__filial").get(pk=self.lote_id)
        erros = {}

        if self.filial_destino_id and lote.estoque.filial_id == self.filial_destino_id:
            erros["filial_destino"] = "A filial de destino é a mesma filial do lote de origem."

        if self.quantidade and self.quantidade > lote.quantidade_atual:
            erros["quantidade"] = (
                f"Saldo insuficiente no lote. Disponível: {lote.quantidade_atual}, "
                f"solicitado: {self.quantidade}."
            )

        if erros:
            raise ValidationError(erros)

    def save(self, *args, **kwargs):
        # Enquanto pendente, produto, origem e preço acompanham o lote escolhido
        if self.status == "pendente" and self.lote_id:
            lote = Lote.objects.select_related("estoque").get(pk=self.lote_id)
            self.produto_id = lote.estoque.produto_id
            self.filial_origem_id = lote.estoque.filial_id
            self.preco_unitario = lote.preco_unitario
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Fluxo
    # ------------------------------------------------------------------
    def confirmar_transferencia(self, usuario):
        """Tira a quantidade do lote de origem e cria um lote na filial de destino."""
        with transaction.atomic():
            # Trava a transferência: evita que duas pessoas confirmem ao mesmo tempo
            atual = TransferenciaEstoque.objects.select_for_update().get(pk=self.pk)
            if atual.status != "pendente":
                raise ValidationError("Só é possível confirmar transferências pendentes.")

            # 1. Trava o lote de origem e confere o saldo neste momento
            lote_origem = Lote.objects.select_for_update().get(pk=atual.lote_id)
            if atual.quantidade > lote_origem.quantidade_atual:
                raise ValidationError(
                    f"Saldo insuficiente no lote de origem. Disponível: {lote_origem.quantidade_atual}, "
                    f"solicitado: {atual.quantidade}."
                )

            # 2. Desconta da origem
            lote_origem.quantidade_atual -= atual.quantidade
            lote_origem.save(update_fields=["quantidade_atual"])

            # 3. Estoque de destino (cria se ainda não existir)
            estoque_destino, _ = Estoque.objects.get_or_create(
                produto_id=atual.produto_id,
                filial_id=atual.filial_destino_id,
            )

            # 4. Novo lote no destino, com o mesmo custo e documentos da origem
            lote_destino = Lote.objects.create(
                estoque=estoque_destino,
                fornecedor=lote_origem.fornecedor,
                nf=lote_origem.nf,
                chave=lote_origem.chave,
                preco_unitario=lote_origem.preco_unitario,
                quantidade_entrada=atual.quantidade,
                data_entrada=timezone.localdate(),
            )

            # 5. Fecha a transferência
            atual.status = "confirmada"
            atual.lote_destino = lote_destino
            atual.confirmado_por = usuario
            atual.data_confirmacao = timezone.now()
            atual.save()

        # Atualiza o objeto em memória com o que foi gravado
        self.refresh_from_db()
        return self

    def cancelar_transferencia(self, usuario):
        """Cancela uma transferência pendente (não mexe no estoque)."""
        with transaction.atomic():
            atual = TransferenciaEstoque.objects.select_for_update().get(pk=self.pk)
            if atual.status != "pendente":
                raise ValidationError("Só é possível cancelar transferências pendentes.")
            atual.status = "cancelada"
            atual.confirmado_por = usuario
            atual.data_confirmacao = timezone.now()
            atual.save()

        self.refresh_from_db()
        return self