"""Fórmula única de multa/juros por atraso de uma cobrança.

Usada pelas mensagens do cron do A2 (app/agents/a2_cobranca/mensagens.py) e
pela tool de status de cobrança do A1 (app/agents/a1_atendimento/atendimento.py),
pra que o valor atualizado informado ao inquilino seja o mesmo nos dois
lugares. O painel (frontend/src/components/gestao/CobrancasSection.tsx:
calcularValorFinal) tem uma cópia em TypeScript — manter em sincronia se a
fórmula mudar.

Nada disso é persistido: charges só guarda valor_esperado e dias_atraso
(atualizado todo dia pelo cron), e o valor com encargos é sempre derivado
na hora.
"""


def calcular_encargos(
    valor_esperado: float,
    dias_atraso: int,
    multa_moratoria_percentual: float | None,
    juros_moratorio_mensal: float,
) -> tuple[float, float, float]:
    """Multa é flat (não proporcional aos dias); juros é prorateado por dia
    num mês de 30 dias — convenção assumida, não especificada na doc.
    multa_moratoria_percentual é fração (0.02 = 2%), não percentual inteiro
    — ver nota de unidade em Migration 011, ainda não validada contra dado
    real."""
    percentual_multa = multa_moratoria_percentual or 0.0
    valor_multa = valor_esperado * percentual_multa
    valor_juros = valor_esperado * juros_moratorio_mensal * (dias_atraso / 30)
    valor_total = valor_esperado + valor_multa + valor_juros
    return round(valor_multa, 2), round(valor_juros, 2), round(valor_total, 2)
