from datetime import date

import pytest

from app.tools.mensagens_gestao_contratual import (
    formatar_data_br,
    formatar_moeda_brl,
    formatar_percentual_br,
    montar_alerta_renovacao,
    montar_calculo_reajuste,
)


def test_formatar_data_br():
    assert formatar_data_br(date(2026, 9, 13)) == "13/09/2026"


def test_formatar_moeda_brl():
    assert formatar_moeda_brl(1500.0) == "1.500,00"
    assert formatar_moeda_brl(1234567.89) == "1.234.567,89"
    assert formatar_moeda_brl(950.5) == "950,50"


def test_formatar_percentual_br():
    assert formatar_percentual_br(3.1776989201364847) == "3,18"


def test_montar_alerta_renovacao_reproduz_template():
    mensagem = montar_alerta_renovacao(
        identificacao_imovel="Apto 302, Ed. X",
        nome_inquilino="João Silva",
        periodo_contrato="12 meses",
        data_aniversario_contrato=date(2026, 9, 13),
    )

    assert mensagem == (
        "@Domingos Monteiro @Fernanda Monteiro, o contrato do Apto 302, Ed. X (João Silva) completa "
        "12 meses no dia 13/09/2026, daqui a 60 dias.\n\n"
        "Será necessário tomar a decisão quanto à renovação, renegociação ou encerramento do contrato."
    )


def test_montar_calculo_reajuste_reproduz_template():
    mensagem = montar_calculo_reajuste(
        identificacao_imovel="Apto 302, Ed. X",
        nome_inquilino="João Silva",
        data_aniversario_contrato=date(2026, 8, 14),
        indice_reajuste="igpm",
        numero_clausula_reajuste="5.2",
        valor_atual=1500.0,
        percentual_reajuste=3.18,
        valor_reajustado=1547.7,
    )

    assert mensagem == (
        "@Domingos Monteiro @Fernanda Monteiro, segue o cálculo de reajuste do contrato do Apto 302, "
        "Ed. X (João Silva), com data de aniversário em 14/08/2026.\n\n"
        "Índice aplicável (conforme cláusula 5.2): IGPM\n"
        "Valor atual do aluguel: R$ 1.500,00\n"
        "Percentual de reajuste: 3,18%\n"
        "Novo valor sugerido: R$ 1.547,70"
    )


def test_montar_calculo_reajuste_sem_clausula_identificada():
    mensagem = montar_calculo_reajuste(
        identificacao_imovel="Apto 302, Ed. X",
        nome_inquilino="João Silva",
        data_aniversario_contrato=date(2026, 8, 14),
        indice_reajuste="ipca",
        numero_clausula_reajuste=None,
        valor_atual=1500.0,
        percentual_reajuste=4.5,
        valor_reajustado=1567.5,
    )

    assert "cláusula não identificada" in mensagem
    assert "IPCA" in mensagem


def test_montar_calculo_reajuste_rejeita_livre_negociacao():
    with pytest.raises(ValueError, match="livre_negociacao"):
        montar_calculo_reajuste(
            identificacao_imovel="Apto 302, Ed. X",
            nome_inquilino="João Silva",
            data_aniversario_contrato=date(2026, 8, 14),
            indice_reajuste="livre_negociacao",
            numero_clausula_reajuste="5.2",
            valor_atual=1500.0,
            percentual_reajuste=3.0,
            valor_reajustado=1545.0,
        )
