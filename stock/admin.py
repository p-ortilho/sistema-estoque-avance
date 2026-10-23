from decimal import Decimal

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import reverse
from django.db.models import DecimalField, ExpressionWrapper, F, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

from stock.models import AplicacaoEstoque, ConsumoGeral, Equipamento, Estoque, Filial, Lote, Produto, TransferenciaEstoque


def filiais_do_usuario(user):
    """Filiais que o usuário pode movimentar. None = todas (superusuário)."""
    if user.is_superuser:
        return None
    perfil = getattr(user, "perfil", None)
    if perfil is None:
        return Filial.objects.none()
    return perfil.filiais.all()


class FiltroPorFilialMixin:
    """
    Mostra só os registros das filiais do usuário (definidas no Perfil).
    Superusuário vê tudo; usuário sem perfil não vê nada.
    `campo_filial` é o caminho até a filial, ex.: "filial" ou "estoque__filial".
    """

    campo_filial = None

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        filiais = filiais_do_usuario(request.user)
        if filiais is None:
            return qs
        return qs.filter(**{f"{self.campo_filial}__in": filiais})


class LoteComSaldoMixin:
    """
    No campo "lote", só oferece lotes com saldo.
    Exceção: na edição, o lote já gravado continua aceito, mesmo que tenha
    zerado (senão não daria para corrigir uma aplicação que usou o último saldo).
    Vale para o select comum e para o campo com pesquisa (autocomplete).
    """

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        campo = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == "lote" and campo is not None:
            filtro = Q(quantidade_atual__gt=0)
            object_id = request.resolver_match.kwargs.get("object_id") if request.resolver_match else None
            if object_id:
                lote_atual = (
                    self.model.objects.filter(pk=object_id).values_list("lote_id", flat=True).first()
                )
                if lote_atual:
                    filtro |= Q(pk=lote_atual)
            campo.queryset = campo.queryset.filter(filtro)
        return campo


def formatar_reais(valor):
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


# ---------------------------------------------------------------------------
# Filial
# ---------------------------------------------------------------------------
@admin.register(Filial)
class FilialAdmin(ModelAdmin):
    list_display = ("codigo", "nome", "ativa", "criado_em")
    list_filter = ("ativa",)
    search_fields = ("codigo", "nome")


# ---------------------------------------------------------------------------
# Produto
# ---------------------------------------------------------------------------
@admin.register(Produto)
class ProdutoAdmin(ModelAdmin):
    list_display = ("codigo", "nome", "categoria", "ativo")
    list_filter = ("categoria", "ativo")
    search_fields = ("codigo", "nome")


# ---------------------------------------------------------------------------
# Estoque + Lotes (inline)
# ---------------------------------------------------------------------------
class LoteInline(TabularInline):
    model = Lote
    extra = 1  # uma linha em branco pronta para nova entrada
    fields = (
        "data_entrada",
        "fornecedor",
        "nf",
        "chave",
        "preco_unitario",
        "quantidade_entrada",
        "quantidade_atual",
    )
    readonly_fields = ("quantidade_atual",)
    ordering = ("-data_entrada", "-id")  # entradas mais recentes no topo
    show_change_link = True  # link para abrir o lote na tela própria


@admin.register(Estoque)
class EstoqueAdmin(FiltroPorFilialMixin, ModelAdmin):
    campo_filial = "filial"
    inlines = [LoteInline]

    list_display = (
        "produto",
        "filial",
        "exibir_quantidade",
        "quantidade_minima",
        "exibir_valor_total",
        "situacao",
    )
    list_filter = ("filial",)
    search_fields = ("produto__nome", "filial__nome")
    list_select_related = ("produto", "filial")

    fields = (
        "produto",
        "filial",
        "quantidade_minima",
        "exibir_quantidade",
        "exibir_valor_total",
        "atualizado_em",
    )
    readonly_fields = ("exibir_quantidade", "exibir_valor_total", "atualizado_em")

    def get_queryset(self, request):
        # Calcula os totais direto no banco, em uma única consulta
        valor_lote = ExpressionWrapper(
            F("lotes__quantidade_atual") * F("lotes__preco_unitario"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        return super().get_queryset(request).annotate(
            qtd_total=Coalesce(
                Sum("lotes__quantidade_atual"), 0, output_field=IntegerField()
            ),
            valor_estoque=Coalesce(
                Sum(valor_lote),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "filial":
            # Só pode criar estoque nas próprias filiais
            filiais = filiais_do_usuario(request.user)
            kwargs["queryset"] = Filial.objects.filter(ativa=True) if filiais is None else filiais.filter(ativa=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        campos = list(super().get_readonly_fields(request, obj))
        if obj:  # depois de criado, produto e filial não podem mudar
            campos += ["produto", "filial"]
        return campos

    @display(description="Quantidade", ordering="qtd_total")
    def exibir_quantidade(self, obj):
        if not obj.pk:
            return "-"
        return obj.qtd_total

    @display(description="Valor total", ordering="valor_estoque")
    def exibir_valor_total(self, obj):
        if not obj.pk:
            return "-"
        return formatar_reais(obj.valor_estoque)

    @display(
        description="Situação",
        label={"Estoque baixo": "danger", "OK": "success"},
    )
    def situacao(self, obj):
        return "Estoque baixo" if obj.qtd_total <= obj.quantidade_minima else "OK"


# ---------------------------------------------------------------------------
# Lote
# ---------------------------------------------------------------------------
@admin.register(Lote)
class LoteAdmin(FiltroPorFilialMixin, ModelAdmin):
    campo_filial = "estoque__filial"
    list_display = (
        "data_entrada",
        "estoque",
        "nf",
        "fornecedor",
        "exibir_preco",
        "quantidade_entrada",
        "quantidade_atual",
    )
    list_filter = ("estoque__filial", "data_entrada")
    search_fields = ("nf", "chave", "fornecedor", "estoque__produto__nome")
    list_select_related = ("estoque__produto", "estoque__filial")
    autocomplete_fields = ("estoque",)  # campo de busca em vez de lista gigante
    date_hierarchy = "data_entrada"

    fields = (
        "estoque",
        "data_entrada",
        "fornecedor",
        "nf",
        "chave",
        "preco_unitario",
        "quantidade_entrada",
        "quantidade_atual",
    )
    readonly_fields = ("quantidade_atual",)

    @display(description="Preço unitário", ordering="preco_unitario")
    def exibir_preco(self, obj):
        return formatar_reais(obj.preco_unitario)

    def get_queryset(self, request):
        # O __str__ do lote usa produto e filial; evita uma consulta por lote
        return super().get_queryset(request).select_related("estoque__produto", "estoque__filial")

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        # Nos campos "Lote" da Aplicação e da Transferência, mostra só lotes com saldo.
        # (A restrição por filial já vem do get_queryset, via FiltroPorFilialMixin.)
        if request.GET.get("model_name") in ("aplicacaoestoque", "consumogeral", "transferenciaestoque"):
            queryset = queryset.filter(quantidade_atual__gt=0)
        return queryset, use_distinct

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "estoque":
            filiais = filiais_do_usuario(request.user)
            if filiais is not None:
                kwargs["queryset"] = Estoque.objects.filter(filial__in=filiais)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ---------------------------------------------------------------------------
# Equipamento
# ---------------------------------------------------------------------------
@admin.register(Equipamento)
class EquipamentoAdmin(ModelAdmin):
    list_display = ("nome", "numero_serie", "tipo", "status")
    list_filter = ("tipo", "status")
    search_fields = ("nome", "numero_serie")  # necessário para o autocomplete da Aplicação
    ordering = ("nome",)  # lista e busca sempre em ordem alfabética


# ---------------------------------------------------------------------------
# Aplicação de estoque (baixa nos lotes)
# ---------------------------------------------------------------------------
@admin.register(AplicacaoEstoque)
class AplicacaoEstoqueAdmin(LoteComSaldoMixin, FiltroPorFilialMixin, ModelAdmin):
    campo_filial = "lote__estoque__filial"
    list_display = (
        "data_aplicacao",
        "equipamento",
        "produto",
        "filial",
        "lote_nf",
        "quantidade",
        "exibir_preco",
        "exibir_valor_total",
        "aplicado_por",
    )
    list_filter = ("lote__estoque__filial", "equipamento", "produto", "data_aplicacao")  # filial vem do lote
    search_fields = ("equipamento__nome", "produto__nome", "lote__nf", "observacao")
    list_select_related = ("equipamento", "produto", "lote__estoque__filial", "aplicado_por")
    autocomplete_fields = ("equipamento", "lote")
    date_hierarchy = "data_aplicacao"

    fields = (
        "equipamento",
        "lote",
        "quantidade",
        "observacao",
        "produto",
        "exibir_preco",
        "exibir_valor_total",
        "aplicado_por",
        "data_aplicacao",
    )
    readonly_fields = (
        "produto",
        "exibir_preco",
        "exibir_valor_total",
        "aplicado_por",
        "data_aplicacao",
    )

    @display(description="Filial", ordering="lote__estoque__filial__nome")
    def filial(self, obj):
        return obj.lote.estoque.filial

    @display(description="NF do lote", ordering="lote__nf")
    def lote_nf(self, obj):
        return obj.lote.nf or "-"

    @display(description="Preço unitário", ordering="preco_unitario_aplicado")
    def exibir_preco(self, obj):
        if not obj.pk:
            return "-"
        return formatar_reais(obj.preco_unitario_aplicado)

    @display(description="Valor total")
    def exibir_valor_total(self, obj):
        if not obj.pk:
            return "-"
        return formatar_reais(obj.valor_total)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "lote":
            # Só pode aplicar lotes das próprias filiais
            filiais = filiais_do_usuario(request.user)
            if filiais is not None:
                kwargs["queryset"] = Lote.objects.filter(estoque__filial__in=filiais)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.aplicado_por = request.user  # usuário logado
        super().save_model(request, obj, form, change)

    def get_actions(self, request):
        # A exclusão em massa não passa pelo delete() da model e não devolveria
        # a quantidade ao lote. Excluir só pela tela de cada aplicação.
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


# ---------------------------------------------------------------------------
# Consumo geral (produto usado em vários equipamentos, sem um equipamento específico)
# ---------------------------------------------------------------------------
@admin.register(ConsumoGeral)
class ConsumoGeralAdmin(LoteComSaldoMixin, FiltroPorFilialMixin, ModelAdmin):
    campo_filial = "lote__estoque__filial"

    list_display = (
        "data_consumo",
        "finalidade",
        "produto",
        "filial",
        "lote_nf",
        "quantidade",
        "exibir_preco",
        "exibir_valor_total",
        "registrado_por",
    )
    list_filter = ("lote__estoque__filial", "produto", "data_consumo")
    search_fields = ("finalidade", "produto__nome", "lote__nf", "observacao")
    list_select_related = ("produto", "lote__estoque__filial", "registrado_por")
    autocomplete_fields = ("lote",)
    date_hierarchy = "data_consumo"

    fields = (
        "lote",
        "quantidade",
        "finalidade",
        "observacao",
        "produto",
        "exibir_preco",
        "exibir_valor_total",
        "registrado_por",
        "data_consumo",
    )
    readonly_fields = (
        "produto",
        "exibir_preco",
        "exibir_valor_total",
        "registrado_por",
        "data_consumo",
    )

    @display(description="Filial", ordering="lote__estoque__filial__nome")
    def filial(self, obj):
        return obj.lote.estoque.filial

    @display(description="NF do lote", ordering="lote__nf")
    def lote_nf(self, obj):
        return obj.lote.nf or "-"

    @display(description="Preço unitário", ordering="preco_unitario_aplicado")
    def exibir_preco(self, obj):
        if not obj.pk:
            return "-"
        return formatar_reais(obj.preco_unitario_aplicado)

    @display(description="Valor total")
    def exibir_valor_total(self, obj):
        if not obj.pk:
            return "-"
        return formatar_reais(obj.valor_total)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "lote":
            # Só pode consumir lotes das próprias filiais
            filiais = filiais_do_usuario(request.user)
            if filiais is not None:
                kwargs["queryset"] = Lote.objects.filter(estoque__filial__in=filiais)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.registrado_por = request.user  # usuário logado
        super().save_model(request, obj, form, change)

    def get_actions(self, request):
        # A exclusão em massa não passa pelo delete() da model e não devolveria
        # a quantidade ao lote. Excluir só pela tela de cada consumo.
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


# ---------------------------------------------------------------------------
# Transferência entre filiais
# ---------------------------------------------------------------------------
@admin.register(TransferenciaEstoque)
class TransferenciaEstoqueAdmin(LoteComSaldoMixin, ModelAdmin):
    list_display = (
        "data_solicitacao",
        "produto",
        "filial_origem",
        "filial_destino",
        "quantidade",
        "exibir_preco",
        "exibir_valor_total",
        "exibir_status",
        "solicitado_por",
    )
    list_filter = ("status", "filial_origem", "filial_destino")
    search_fields = ("produto__nome", "lote__nf")
    list_select_related = ("produto", "filial_origem", "filial_destino", "solicitado_por")
    autocomplete_fields = ("lote",)
    actions = ["confirmar_transferencias", "cancelar_transferencias"]
    actions_detail = ["confirmar_detalhe", "cancelar_detalhe"]  # botões na tela da transferência

    campos_editaveis = ("lote", "filial_destino", "quantidade", "observacao")
    campos_informativos = (
        "produto",
        "filial_origem",
        "exibir_preco",
        "exibir_valor_total",
        "exibir_status",
        "lote_destino",
        "solicitado_por",
        "data_solicitacao",
        "confirmado_por",
        "data_confirmacao",
    )
    fields = campos_editaveis + campos_informativos

    # ----- Exibição -----
    @display(description="Preço unitário", ordering="preco_unitario")
    def exibir_preco(self, obj):
        if not obj.pk:
            return "-"
        return formatar_reais(obj.preco_unitario)

    @display(description="Valor total")
    def exibir_valor_total(self, obj):
        if not obj.pk:
            return "-"
        return formatar_reais(obj.valor_total)

    @display(
        description="Status",
        ordering="status",
        label={"Pendente": "warning", "Confirmada": "success", "Cancelada": "danger"},
    )
    def exibir_status(self, obj):
        if not obj.pk:
            return "-"
        return obj.get_status_display()

    # ----- Permissões e filtros -----
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        filiais = filiais_do_usuario(request.user)
        if filiais is None:
            return qs
        return qs.filter(Q(filial_origem__in=filiais) | Q(filial_destino__in=filiais))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "filial_destino":
            # Pode enviar para qualquer filial ativa
            kwargs["queryset"] = Filial.objects.filter(ativa=True)
        if db_field.name == "lote":
            # Só pode tirar de lotes das próprias filiais
            filiais = filiais_do_usuario(request.user)
            if filiais is not None:
                kwargs["queryset"] = Lote.objects.filter(estoque__filial__in=filiais)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def _eh_da_origem(self, user, transferencia):
        filiais = filiais_do_usuario(user)
        return filiais is None or filiais.filter(pk=transferencia.filial_origem_id).exists()

    def get_readonly_fields(self, request, obj=None):
        if obj and (obj.status != "pendente" or not self._eh_da_origem(request.user, obj)):
            # Confirmada/cancelada vira histórico; a filial de destino só consulta e confirma
            return self.campos_editaveis + self.campos_informativos
        return self.campos_informativos

    def has_delete_permission(self, request, obj=None):
        # Só a filial de origem exclui, e só enquanto estiver pendente
        if obj and (obj.status != "pendente" or not self._eh_da_origem(request.user, obj)):
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)  # evita apagar histórico em massa
        return actions

    def save_model(self, request, obj, form, change):
        if not change:
            obj.solicitado_por = request.user
        super().save_model(request, obj, form, change)

    # ----- Confirmar / cancelar -----
    def has_transferencia_pendente_permission(self, request, object_id=None):
        # Os botões de confirmar/cancelar só aparecem enquanto a transferência está pendente
        if object_id is None:
            return True
        return self.get_queryset(request).filter(pk=object_id, status="pendente").exists()

    def _pode_confirmar(self, user, transferencia):
        # Quem confirma é quem recebe: usuário da filial de destino (ou superusuário)
        filiais = filiais_do_usuario(user)
        return filiais is None or filiais.filter(pk=transferencia.filial_destino_id).exists()

    def _executar(self, request, transferencias, operacao):
        concluidas = 0
        for transferencia in transferencias:
            if operacao == "confirmar" and not self._pode_confirmar(request.user, transferencia):
                messages.error(
                    request,
                    f"{transferencia}: só um usuário da filial de destino pode confirmar o recebimento.",
                )
                continue
            try:
                if operacao == "confirmar":
                    transferencia.confirmar_transferencia(request.user)
                else:
                    transferencia.cancelar_transferencia(request.user)
                concluidas += 1
            except ValidationError as erro:
                messages.error(request, f"{transferencia}: {' '.join(erro.messages)}")
        return concluidas

    @admin.action(description="Confirmar transferências selecionadas")
    def confirmar_transferencias(self, request, queryset):
        feitas = self._executar(request, queryset.filter(status="pendente"), "confirmar")
        if feitas:
            messages.success(request, f"{feitas} transferência(s) confirmada(s) e estoque atualizado.")

    @admin.action(description="Cancelar transferências selecionadas")
    def cancelar_transferencias(self, request, queryset):
        feitas = self._executar(request, queryset.filter(status="pendente"), "cancelar")
        if feitas:
            messages.success(request, f"{feitas} transferência(s) cancelada(s).")

    @action(description="Confirmar recebimento", url_path="confirmar", permissions=["transferencia_pendente"])
    def confirmar_detalhe(self, request, object_id):
        transferencia = self.get_object(request, object_id)
        if transferencia and self._executar(request, [transferencia], "confirmar"):
            messages.success(request, "Transferência confirmada e estoque atualizado.")
        return redirect(reverse("admin:stock_transferenciaestoque_change", args=[object_id]))

    @action(description="Cancelar transferência", url_path="cancelar", permissions=["transferencia_pendente"])
    def cancelar_detalhe(self, request, object_id):
        transferencia = self.get_object(request, object_id)
        if transferencia and self._executar(request, [transferencia], "cancelar"):
            messages.success(request, "Transferência cancelada.")
        return redirect(reverse("admin:stock_transferenciaestoque_change", args=[object_id]))