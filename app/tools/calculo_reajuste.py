import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from app.tools.text_matching import normalizar

# Radicais, não palavras inteiras: cláusulas variam a flexão ("reajuste",
# "reajustado", "reajustar"), então aqui queremos substring mesmo — diferente
# de contem_palavra (usada em fluxo.py/maintenance_classification.py), que
# exige palavra inteira para evitar falso positivo em palavras não
# relacionadas (ex: "gas" em "gastei").
_RADICAIS_CLAUSULA_REAJUSTE = ("reajust", "indice", "correcao monetaria")


def esta_na_janela_alerta_renovacao(data_termino: date, hoje: date, dias_antecedencia: int = 60) -> bool:
    """Fluxo A: true no dia exato em que faltam `dias_antecedencia` para o
    término da vigência do contrato."""
    return (data_termino - hoje) == timedelta(days=dias_antecedencia)


def calcular_periodo_contrato_meses(data_inicio: date, data_termino: date) -> str:
    """Duração total do contrato em meses inteiros, para a mensagem de alerta
    de renovação (ex: '12 meses', '30 meses').

    Compara o dia de data_inicio contra o ÚLTIMO DIA do mês de data_termino,
    não contra data_inicio.day cru — senão um contrato de 31/01 a 30/04 (3
    meses corridos, abril só tem 30 dias) seria contado como "2 meses": o
    dia 31 nunca existe em abril, então 30/04 já é o equivalente mais
    próximo do aniversário mensal, não um dia "faltando"."""
    meses = (data_termino.year - data_inicio.year) * 12 + (data_termino.month - data_inicio.month)
    ultimo_dia_mes_termino = calendar.monthrange(data_termino.year, data_termino.month)[1]
    dia_inicio_efetivo = min(data_inicio.day, ultimo_dia_mes_termino)
    if data_termino.day < dia_inicio_efetivo:
        meses -= 1
    return f"{meses} meses"


def proximo_aniversario_contrato(data_inicio: date, hoje: date) -> date:
    """Próxima data de aniversário anual do contrato (mesmo dia/mês de
    data_inicio) a partir de hoje, inclusive. 29/02 em ano não bissexto cai
    para 28/02 — mais simples e previsível que herdar o overflow do Python
    para março."""

    def _aniversario_no_ano(ano: int) -> date:
        try:
            return data_inicio.replace(year=ano)
        except ValueError:
            return data_inicio.replace(year=ano, day=28)

    candidato = _aniversario_no_ano(hoje.year)
    if candidato < hoje:
        candidato = _aniversario_no_ano(hoje.year + 1)
    return candidato


def esta_na_janela_calculo_reajuste(data_inicio: date, hoje: date, dias_antecedencia: int = 30) -> bool:
    """Fluxo B: true no dia exato em que faltam `dias_antecedencia` para o
    próximo aniversário anual do contrato."""
    aniversario = proximo_aniversario_contrato(data_inicio, hoje)
    return (aniversario - hoje) == timedelta(days=dias_antecedencia)


def calcular_valor_reajustado(valor_atual: float, percentual_reajuste: float) -> float:
    """Usa Decimal, não round() em float puro: round() do Python usa
    representação binária (ex: round(2.675, 2) == 2.67, não 2.68, porque
    2.675 não é exatamente representável em binário) — inaceitável para um
    valor que vira contracts.valor_aluguel de verdade."""
    fator = Decimal("1") + Decimal(str(percentual_reajuste)) / Decimal("100")
    valor = Decimal(str(valor_atual)) * fator
    return float(valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def identificar_clausula_reajuste(clausulas: list[tuple[str, str]]) -> Optional[str]:
    """Procura, entre as cláusulas financeiras do contrato, a primeira que
    menciona reajuste/índice/correção monetária — para citar o número na
    mensagem à gestora. `clausulas` é uma lista de (numero_clausula,
    texto_clausula), já filtrada por categoria='financeiro' (ver
    app/tools/contract_alerts_client.py::listar_clausulas_financeiras)."""
    for numero_clausula, texto_clausula in clausulas:
        texto_normalizado = normalizar(texto_clausula)
        if any(radical in texto_normalizado for radical in _RADICAIS_CLAUSULA_REAJUSTE):
            return numero_clausula
    return None
