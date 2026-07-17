from datetime import date

from app.tools.calculo_reajuste import (
    calcular_periodo_contrato_meses,
    calcular_valor_reajustado,
    esta_na_janela_alerta_renovacao,
    esta_na_janela_calculo_reajuste,
    identificar_clausula_reajuste,
    proximo_aniversario_contrato,
)


class TestEstaNaJanelaAlertaRenovacao:
    def test_true_exatamente_60_dias_antes(self):
        assert esta_na_janela_alerta_renovacao(date(2026, 9, 13), date(2026, 7, 15))

    def test_false_59_dias_antes(self):
        assert not esta_na_janela_alerta_renovacao(date(2026, 9, 12), date(2026, 7, 15))

    def test_false_61_dias_antes(self):
        assert not esta_na_janela_alerta_renovacao(date(2026, 9, 14), date(2026, 7, 15))

    def test_false_depois_do_vencimento(self):
        assert not esta_na_janela_alerta_renovacao(date(2026, 7, 1), date(2026, 7, 15))


class TestCalcularPeriodoContratoMeses:
    def test_meses_exatos(self):
        assert calcular_periodo_contrato_meses(date(2025, 1, 15), date(2026, 1, 15)) == "12 meses"

    def test_30_meses(self):
        assert calcular_periodo_contrato_meses(date(2024, 1, 15), date(2026, 7, 15)) == "30 meses"

    def test_dia_final_menor_que_dia_inicial_desconta_um_mes(self):
        # 31/01 -> 15/03 é menos de 2 meses completos (dia 15 < dia 31)
        assert calcular_periodo_contrato_meses(date(2026, 1, 31), date(2026, 3, 15)) == "1 meses"

    def test_dia_31_contra_mes_final_curto_nao_desconta_indevidamente(self):
        # 31/01 -> 30/04: 3 meses corridos (abril não tem dia 31, então 30/04
        # já É o aniversário mensal daquele mês — não "falta 1 dia").
        assert calcular_periodo_contrato_meses(date(2026, 1, 31), date(2026, 4, 30)) == "3 meses"

    def test_dia_29_fevereiro_contra_fevereiro_nao_bissexto(self):
        # 29/02/2024 (bissexto) -> 28/02/2025 (não bissexto): 12 meses, não 11.
        assert calcular_periodo_contrato_meses(date(2024, 2, 29), date(2025, 2, 28)) == "12 meses"


class TestProximoAniversarioContrato:
    def test_ainda_no_primeiro_ano_do_contrato(self):
        # contrato começou há poucos meses: aniversário é 1 ano após o início
        assert proximo_aniversario_contrato(date(2026, 1, 15), date(2026, 6, 1)) == date(2027, 1, 15)

    def test_aniversario_ja_passou_esse_ano_pula_pro_proximo(self):
        assert proximo_aniversario_contrato(date(2020, 3, 1), date(2026, 7, 15)) == date(2027, 3, 1)

    def test_aniversario_ainda_nao_chegou_esse_ano(self):
        assert proximo_aniversario_contrato(date(2020, 12, 1), date(2026, 7, 15)) == date(2026, 12, 1)

    def test_29_fevereiro_em_ano_nao_bissexto_vira_28(self):
        assert proximo_aniversario_contrato(date(2020, 2, 29), date(2026, 1, 1)) == date(2026, 2, 28)


class TestEstaNaJanelaCalculoReajuste:
    def test_true_exatamente_30_dias_antes_do_aniversario(self):
        # aniversário 2026-08-14, hoje = 30 dias antes
        assert esta_na_janela_calculo_reajuste(date(2020, 8, 14), date(2026, 7, 15))

    def test_false_fora_da_janela(self):
        assert not esta_na_janela_calculo_reajuste(date(2020, 8, 20), date(2026, 7, 15))


class TestCalcularValorReajustado:
    def test_calcula_percentual_positivo(self):
        assert calcular_valor_reajustado(1000.0, 5.0) == 1050.0

    def test_arredondamento_meio_para_cima_nao_sofre_imprecisao_binaria(self):
        # round() em float puro dá 2.67 aqui (2.675 não é exato em binário);
        # com Decimal + ROUND_HALF_UP o resultado correto é 2.68.
        assert calcular_valor_reajustado(2.675, 0.0) == 2.68

    def test_arredonda_para_duas_casas(self):
        assert calcular_valor_reajustado(1000.0, 3.1776989201364847) == 1031.78


class TestIdentificarClausulaReajuste:
    def test_encontra_clausula_por_palavra_chave(self):
        clausulas = [
            ("3", "O valor do aluguel será pago até o dia 5 de cada mês."),
            ("3.1", "O aluguel será reajustado anualmente pelo IGPM."),
        ]
        assert identificar_clausula_reajuste(clausulas) == "3.1"

    def test_nao_casa_substring_de_outra_palavra(self):
        # "índice" não deveria casar com uma palavra qualquer que contenha "índic" como prefixo acidental
        clausulas = [("3", "O aluguel é pago via PIX ou depósito em conta.")]
        assert identificar_clausula_reajuste(clausulas) is None

    def test_nenhuma_clausula_menciona_reajuste(self):
        clausulas = [("5", "O inquilino é responsável pela conservação do imóvel.")]
        assert identificar_clausula_reajuste(clausulas) is None
