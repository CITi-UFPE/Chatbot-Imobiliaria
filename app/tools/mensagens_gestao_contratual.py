from datetime import date
from typing import Optional

from app.models.contract_alerts import IndiceReajuste

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
        f"O contrato do {identificacao_imovel}, vinculado a {nome_inquilino}, completa "
        f"{periodo_contrato} em {formatar_data_br(data_aniversario_contrato)}. "
        "Faltam 60 dias para o término.\n\n"
        "Definição necessária: renovação, renegociação ou encerramento."
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
        f"Contrato: {identificacao_imovel}\n"
        f"Inquilino: {nome_inquilino}\n"
        f"Data de aniversário: {formatar_data_br(data_aniversario_contrato)}\n\n"
        f"Índice aplicável (conforme cláusula {clausula_texto}): {_NOME_INDICE[indice_reajuste]}\n"
        f"Valor atual do aluguel: R$ {formatar_moeda_brl(valor_atual)}\n"
        f"Percentual de reajuste: {formatar_percentual_br(percentual_reajuste)}%\n"
        f"Valor calculado após o reajuste: R$ {formatar_moeda_brl(valor_reajustado)}"
    )
