"""Testes da fórmula única de multa/juros por atraso (app/tools/encargos_atraso.py),
compartilhada pelas mensagens do cron do A2 e pela tool de status de cobrança do A1."""

from app.tools.encargos_atraso import calcular_encargos


def test_multa_flat_e_juros_prorateados_por_dia():
    valor_multa, valor_juros, valor_total = calcular_encargos(4300.0, 32, 0.02, 0.01)

    assert valor_multa == 86.0
    assert valor_juros == 45.87  # 4300 * 0.01 * 32/30
    assert valor_total == 4431.87


def test_multa_nula_vira_zero():
    valor_multa, valor_juros, valor_total = calcular_encargos(1000.0, 30, None, 0.01)

    assert valor_multa == 0.0
    assert valor_juros == 10.0
    assert valor_total == 1010.0


def test_mensagens_do_a2_usam_a_mesma_formula():
    """Garante que o A2 não voltou a ter uma cópia própria da fórmula."""
    from app.agents.a2_cobranca import mensagens

    assert mensagens.calcular_encargos is calcular_encargos
