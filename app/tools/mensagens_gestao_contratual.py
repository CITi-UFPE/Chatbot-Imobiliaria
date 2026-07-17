from datetime import date
from typing import Optional

from app.models.contract_alerts import IndiceReajuste

# Nomes fixos: Domingos e Fernanda Monteiro são os únicos gestores do
# portfólio (ver docs/schemas/002_auth_rbac_rls.sql, staff_users) — não há,
# hoje, uma lista de gestores por imóvel para mencionar dinamicamente.
GESTORES_MENCAO = "@Domingos Monteiro @Fernanda Monteiro"

_NOME_INDICE = {"igpm": "IGPM", "ipca": "IPCA"}


def formatar_data_br(data: date) -> str:
    return data.strftime("%d/%m/%Y")


def formatar_moeda_brl(valor: float) -> str:
    inteiro, decimal = f"{valor:,.2f}".split(".")
    return f"{inteiro.replace(',', '.')},{decimal}"


def formatar_percentual_br(valor: float) -> str:
    return f"{valor:.2f}".replace(".", ",")


def montar_alerta_renovacao(
    identificacao_imovel: str,
    nome_inquilino: str,
    periodo_contrato: str,
    data_aniversario_contrato: date,
) -> str:
    return (
        f"{GESTORES_MENCAO}, o contrato do {identificacao_imovel} ({nome_inquilino}) completa "
        f"{periodo_contrato} no dia {formatar_data_br(data_aniversario_contrato)}, daqui a 60 dias.\n\n"
        "Será necessário tomar a decisão quanto à renovação, renegociação ou encerramento do contrato."
    )


def montar_calculo_reajuste(
    identificacao_imovel: str,
    nome_inquilino: str,
    data_aniversario_contrato: date,
    indice_reajuste: IndiceReajuste,
    numero_clausula_reajuste: Optional[str],
    valor_atual: float,
    percentual_reajuste: float,
    valor_reajustado: float,
) -> str:
    """indice_reajuste deve ser 'igpm' ou 'ipca' — contratos com
    indice_reajuste='livre_negociacao' não têm cálculo automático de reajuste
    (Fluxo B não se aplica) e não devem chegar até aqui; ver
    app/agents/a4_gestao_contratual/fluxo.py."""
    if indice_reajuste not in _NOME_INDICE:
        raise ValueError(
            f"montar_calculo_reajuste não se aplica a indice_reajuste={indice_reajuste!r} "
            "(só 'igpm'/'ipca' têm cálculo automático)."
        )

    clausula_texto = numero_clausula_reajuste if numero_clausula_reajuste else "não identificada"

    return (
        f"{GESTORES_MENCAO}, segue o cálculo de reajuste do contrato do {identificacao_imovel} "
        f"({nome_inquilino}), com data de aniversário em {formatar_data_br(data_aniversario_contrato)}.\n\n"
        f"Índice aplicável (conforme cláusula {clausula_texto}): {_NOME_INDICE[indice_reajuste]}\n"
        f"Valor atual do aluguel: R$ {formatar_moeda_brl(valor_atual)}\n"
        f"Percentual de reajuste: {formatar_percentual_br(percentual_reajuste)}%\n"
        f"Novo valor sugerido: R$ {formatar_moeda_brl(valor_reajustado)}"
    )
