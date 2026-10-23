"""
Dados do dashboard (página inicial do admin).

Ligado no settings.py por:  UNFOLD["DASHBOARD_CALLBACK"] = "core.dashboard.dashboard_callback"
Respeita a filial do usuário: cada um vê só os números das filiais do seu Perfil.
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, IntegerField, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.urls import reverse
from django.utils import timezone

from stock.admin import filiais_do_usuario, formatar_reais
from stock.models import AplicacaoEstoque, Estoque, Lote, Produto, TransferenciaEstoque

DINHEIRO = DecimalField(max_digits=16, decimal_places=2)

# Cores das pizzas (paleta categórica validada para daltonismo), sempre na mesma ordem.
# O vermelho da marca fica para os gráficos de uma série só (linha e barras).
CORES_CATEGORIAS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]
COR_OUTROS = "#9ca3af"
MAX_CATEGORIAS = 6  # o restante vira "Outros"


def _numero_br(valor, casas=0):
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _nomes_das_categorias(chaves):
    """Converte o valor salvo em `Produto.categoria` no nome que aparece no gráfico."""
    campo = Produto._meta.get_field("categoria")
    if campo.is_relation:  # categoria é uma ForeignKey
        objetos = campo.related_model.objects.in_bulk([c for c in chaves if c])
        return {c: (str(objetos[c]) if c in objetos else "Sem categoria") for c in chaves}
    escolhas = dict(campo.flatchoices) if campo.choices else {}
    return {c: (escolhas.get(c, c) or "Sem categoria") for c in chaves}


def dashboard_callback(request, context):
    filiais = filiais_do_usuario(request.user)  # None = todas (superusuário)

    lotes = Lote.objects.filter(quantidade_atual__gt=0)
    estoques = Estoque.objects.all()
    aplicacoes = AplicacaoEstoque.objects.all()
    transferencias = TransferenciaEstoque.objects.filter(status="pendente")
    if filiais is not None:
        lotes = lotes.filter(estoque__filial__in=filiais)
        estoques = estoques.filter(filial__in=filiais)
        aplicacoes = aplicacoes.filter(lote__estoque__filial__in=filiais)
        transferencias = transferencias.filter(
            Q(filial_origem__in=filiais) | Q(filial_destino__in=filiais)
        )

    valor_do_lote = ExpressionWrapper(F("quantidade_atual") * F("preco_unitario"), output_field=DINHEIRO)

    # ------------------------------------------------------------------
    # Cards
    # ------------------------------------------------------------------
    valor_total = lotes.aggregate(total=Sum(valor_do_lote))["total"] or Decimal("0")

    estoque_baixo = (
        estoques.annotate(
            qtd=Coalesce(Sum("lotes__quantidade_atual"), 0, output_field=IntegerField())
        )
        .filter(qtd__lte=F("quantidade_minima"))
        .count()
    )
    pendentes = transferencias.count()

    url_estoques = reverse("admin:stock_estoque_changelist")
    url_transferencias = reverse("admin:stock_transferenciaestoque_changelist")

    cards = [
        {
            "titulo": "Valor total em estoque",
            "valor": formatar_reais(valor_total),
            "detalhe": "Saldo dos lotes × preço de entrada",
            "link": url_estoques,
        },
        {
            "titulo": "Itens com estoque baixo",
            "valor": _numero_br(estoque_baixo),
            "detalhe": "No mínimo de alerta ou abaixo dele",
            "link": url_estoques,
            "alerta": estoque_baixo > 0,
        },
        {
            "titulo": "Transferências pendentes",
            "valor": _numero_br(pendentes),
            "detalhe": "Aguardando confirmação ou cancelamento",
            "link": f"{url_transferencias}?status__exact=pendente",
            "alerta": pendentes > 0,
        },
    ]

    # ------------------------------------------------------------------
    # Linha: valor aplicado por dia (últimos 30 dias, incluindo hoje)
    # ------------------------------------------------------------------
    hoje = timezone.localdate()
    primeiro_dia = hoje - timedelta(days=29)
    inicio = timezone.make_aware(
        timezone.datetime.combine(primeiro_dia, timezone.datetime.min.time())
    )

    por_dia = dict(
        aplicacoes.filter(data_aplicacao__gte=inicio)
        .annotate(dia=TruncDate("data_aplicacao", tzinfo=timezone.get_current_timezone()))
        .values("dia")
        .annotate(
            total=Sum(
                ExpressionWrapper(F("quantidade") * F("preco_unitario_aplicado"), output_field=DINHEIRO)
            )
        )
        .values_list("dia", "total")
    )
    dias = [primeiro_dia + timedelta(days=i) for i in range(30)]
    total_aplicado_30d = sum((por_dia.get(d) or 0 for d in dias), Decimal("0"))

    grafico_aplicado = {
        "labels": [d.strftime("%d/%m") for d in dias],
        "datasets": [
            {
                "label": "Valor aplicado (R$)",
                "data": [float(por_dia.get(d) or 0) for d in dias],
                "borderColor": "var(--color-primary-600)",
                "backgroundColor": "var(--color-primary-600)",
                "displayYAxis": True,
                "maxTicksXLimit": 10,
            }
        ],
    }

    # ------------------------------------------------------------------
    # Pizzas: valor e quantidade por categoria
    # ------------------------------------------------------------------
    por_categoria = list(
        lotes.values("estoque__produto__categoria")
        .annotate(valor=Sum(valor_do_lote), qtd=Sum("quantidade_atual"))
        .order_by("-valor")
    )
    nomes = _nomes_das_categorias([c["estoque__produto__categoria"] for c in por_categoria])

    # As cores seguem a categoria (mesma cor nas duas pizzas), ordenadas pelo valor
    principais = por_categoria[:MAX_CATEGORIAS]
    resto = por_categoria[MAX_CATEGORIAS:]
    rotulos = [nomes[c["estoque__produto__categoria"]] for c in principais]
    valores = [float(c["valor"] or 0) for c in principais]
    quantidades = [int(c["qtd"] or 0) for c in principais]
    cores = CORES_CATEGORIAS[: len(principais)]
    if resto:
        rotulos.append("Outros")
        valores.append(float(sum((c["valor"] or 0) for c in resto)))
        quantidades.append(int(sum((c["qtd"] or 0) for c in resto)))
        cores.append(COR_OUTROS)

    def pizza(rotulo, dados):
        return {
            "labels": rotulos,
            "datasets": [{"label": rotulo, "data": dados, "backgroundColor": cores, "borderWidth": 0, "spacing": 2}],
        }

    opcoes_pizza = {
        "responsive": True,
        "maintainAspectRatio": False,
        "animation": False,
        "plugins": {
            "legend": {
                "display": True,
                "position": "bottom",
                "labels": {"usePointStyle": True, "pointStyle": "circle", "boxWidth": 8, "boxHeight": 8, "color": "#6b7280"},
            }
        },
    }

    # Tabela ao lado das pizzas (mostra os números exatos)
    tabela_categorias = {
        "headers": ["Categoria", "Valor", "Quantidade"],
        "rows": [
            [r, formatar_reais(v), _numero_br(q)]
            for r, v, q in zip(rotulos, valores, quantidades)
        ],
    }

    # ------------------------------------------------------------------
    # Barras: valor em estoque por filial
    # ------------------------------------------------------------------
    por_filial = list(
        lotes.values("estoque__filial__nome")
        .annotate(valor=Sum(valor_do_lote))
        .order_by("-valor")
    )
    grafico_filiais = {
        "labels": [f["estoque__filial__nome"] for f in por_filial],
        "datasets": [
            {
                "label": "Valor em estoque (R$)",
                "data": [float(f["valor"] or 0) for f in por_filial],
                "backgroundColor": "var(--color-primary-600)",
                "maxBarThickness": 48,
                "borderRadius": 4,
                "displayYAxis": True,
            }
        ],
    }

    # ------------------------------------------------------------------
    # Barras horizontais: top 10 equipamentos com mais aplicações
    # (todas as aplicações já registradas, das filiais do usuário)
    # ------------------------------------------------------------------
    valor_da_aplicacao = ExpressionWrapper(
        F("quantidade") * F("preco_unitario_aplicado"), output_field=DINHEIRO
    )
    top_equipamentos = list(
        aplicacoes.values("equipamento_id", "equipamento__nome")
        .annotate(aplicacoes=Count("id"), valor=Sum(valor_da_aplicacao))
        .order_by("-aplicacoes", "-valor")[:10]
    )
    grafico_equipamentos = {
        "labels": [e["equipamento__nome"] for e in top_equipamentos],
        "datasets": [
            {
                "label": "Aplicações",
                "data": [e["aplicacoes"] for e in top_equipamentos],
                "backgroundColor": "var(--color-primary-600)",
                "maxBarThickness": 22,
                "borderRadius": 4,
            }
        ],
    }
    # Barras deitadas (nomes legíveis à esquerda). As opções padrão do Unfold
    # são para barras em pé, por isso este gráfico recebe as suas próprias.
    opcoes_equipamentos = {
        "indexAxis": "y",
        "responsive": True,
        "maintainAspectRatio": False,
        "animation": False,
        "plugins": {"legend": {"display": False}},
        "scales": {
            "x": {
                "beginAtZero": True,
                "ticks": {"color": "#9ca3af", "precision": 0},
                "grid": {"color": "rgba(156, 163, 175, .25)"},
                "border": {"display": False},
            },
            "y": {
                "ticks": {"color": "#9ca3af"},
                "grid": {"display": False},
                "border": {"display": False},
            },
        },
    }
    tabela_equipamentos = {
        "headers": ["Equipamento", "Aplicações", "Valor aplicado"],
        "rows": [
            [e["equipamento__nome"], _numero_br(e["aplicacoes"]), formatar_reais(e["valor"] or 0)]
            for e in top_equipamentos
        ],
    }

    context.update(
        {
            "title": "Dashboard",  # texto do cabeçalho da página
            "cards": cards,
            "total_aplicado_30d": formatar_reais(total_aplicado_30d),
            "grafico_aplicado": json.dumps(grafico_aplicado),
            "tem_aplicacoes": total_aplicado_30d > 0,
            "grafico_valor_categoria": json.dumps(pizza("Valor (R$)", valores)),
            "grafico_qtd_categoria": json.dumps(pizza("Quantidade", quantidades)),
            "opcoes_pizza": json.dumps(opcoes_pizza),
            "tabela_categorias": tabela_categorias,
            "tem_categorias": bool(por_categoria),
            "grafico_filiais": json.dumps(grafico_filiais),
            "tem_filiais": bool(por_filial),
            "grafico_equipamentos": json.dumps(grafico_equipamentos),
            "opcoes_equipamentos": json.dumps(opcoes_equipamentos),
            "tabela_equipamentos": tabela_equipamentos,
            "tem_equipamentos": bool(top_equipamentos),
        }
    )
    return context