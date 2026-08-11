"""Testes de unidade do A4 (Gestão Contratual) — dispatcher de renovação
(app/agents/a4_gestao_contratual/fluxo.py::processar_finalizacao_contrato) e
a decisão deliberada de NÃO bloquear o cálculo de reajuste por
prazo_indeterminado (processar_calculo_reajuste).

Não depende de banco nem de rede: as funções testadas recebem os efeitos
colaterais (escrita em contracts, chamada à API de índice) via Callable
injetado, seguindo o padrão que já existe nos docstrings do próprio
fluxo.py ("função pura, testável com fakes injetados").

Rodar: pytest tests/test_fluxo_renovacao.py -v
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.agents.a4_gestao_contratual.fluxo import (
    processar_calculo_reajuste,
    processar_finalizacao_contrato,
)
from app.models.contract_alerts import ContratoParaAlerta

HOJE = date(2026, 3, 10)


def _contrato(
    tipo_renovacao="novo_contrato",
    prazo_indeterminado=False,
    data_termino=HOJE,
    indice_reajuste=None,
    data_inicio=date(2025, 3, 10),
):
    return ContratoParaAlerta(
        id=uuid4(),
        imovel_identificacao="Apto Teste",
        inquilino_nome="Inquilino Teste",
        telefone_whatsapp="+5581999990000",
        data_inicio=data_inicio,
        data_termino=data_termino,
        indice_reajuste=indice_reajuste,
        valor_aluguel=1500.0,
        prazo_indeterminado=prazo_indeterminado,
        tipo_renovacao=tipo_renovacao,
    )


class _ChamadasFinalizacao:
    """Registra quais das 3 funções injetadas foram efetivamente chamadas,
    pra cada teste poder afirmar não só o retorno, mas que o CAMINHO certo
    (e só ele) foi acionado."""

    def __init__(self):
        self.finalizados: list = []
        self.desativados_pendentes: list = []
        self.transicionados: list = []

    def finalizar(self, contract_id):
        self.finalizados.append(contract_id)
        return True

    def desativar_pendente(self, contract_id):
        self.desativados_pendentes.append(contract_id)
        return True

    def transicionar(self, contract_id):
        self.transicionados.append(contract_id)
        return True

    def chamar(self, contrato, hoje):
        return processar_finalizacao_contrato(
            contrato,
            hoje,
            finalizar_contrato_fn=self.finalizar,
            desativar_pendente_renovacao_fn=self.desativar_pendente,
            transicionar_indeterminado_fn=self.transicionar,
        )


# ============================================================
# Dispatcher de renovação — um teste por tipo_renovacao
# ============================================================


def test_novo_contrato_finaliza_normalmente_sem_pendencia():
    chamadas = _ChamadasFinalizacao()
    contrato = _contrato(tipo_renovacao="novo_contrato", data_termino=HOJE)

    resultado = chamadas.chamar(contrato, HOJE)

    assert resultado == ("finalizado", contrato.id)
    assert chamadas.finalizados == [contrato.id]
    assert chamadas.desativados_pendentes == []
    assert chamadas.transicionados == []


@pytest.mark.parametrize("tipo", ["requer_aditivo", "automatica", "nao_identificado"])
def test_tipos_acionaveis_desativam_com_pendencia(tipo):
    chamadas = _ChamadasFinalizacao()
    contrato = _contrato(tipo_renovacao=tipo, data_termino=HOJE)

    resultado = chamadas.chamar(contrato, HOJE)

    assert resultado == ("pendente_renovacao", contrato.id)
    assert chamadas.desativados_pendentes == [contrato.id]
    assert chamadas.finalizados == []
    assert chamadas.transicionados == []


def test_indeterminado_por_lei_transiciona_sem_desativar():
    chamadas = _ChamadasFinalizacao()
    contrato = _contrato(tipo_renovacao="indeterminado_por_lei", data_termino=HOJE)

    resultado = chamadas.chamar(contrato, HOJE)

    assert resultado == ("transicionado_indeterminado", contrato.id)
    assert chamadas.transicionados == [contrato.id]
    assert chamadas.finalizados == []
    assert chamadas.desativados_pendentes == []


def test_prazo_indeterminado_true_nunca_e_tocado_no_vencimento():
    """Contrato já em prazo indeterminado (independente do tipo_renovacao
    original) nunca deve disparar nenhuma das 3 ações — data_termino é
    decorativo pra ele."""
    chamadas = _ChamadasFinalizacao()
    contrato = _contrato(tipo_renovacao="requer_aditivo", prazo_indeterminado=True, data_termino=HOJE)

    resultado = chamadas.chamar(contrato, HOJE)

    assert resultado is None
    assert chamadas.finalizados == chamadas.desativados_pendentes == chamadas.transicionados == []


def test_fora_da_data_termino_nao_faz_nada():
    chamadas = _ChamadasFinalizacao()
    contrato = _contrato(tipo_renovacao="novo_contrato", data_termino=date(2026, 3, 11))

    resultado = chamadas.chamar(contrato, HOJE)

    assert resultado is None
    assert chamadas.finalizados == chamadas.desativados_pendentes == chamadas.transicionados == []


def test_escrita_nao_confirmada_no_banco_devolve_none():
    """Se a função injetada devolver False (guard reforçado no banco não
    bateu no momento exato da escrita), o dispatcher não deve inventar um
    resultado de sucesso."""

    def finalizar_falha(_contract_id):
        return False

    contrato = _contrato(tipo_renovacao="novo_contrato", data_termino=HOJE)

    resultado = processar_finalizacao_contrato(
        contrato,
        HOJE,
        finalizar_contrato_fn=finalizar_falha,
        desativar_pendente_renovacao_fn=lambda _id: True,
        transicionar_indeterminado_fn=lambda _id: True,
    )

    assert resultado is None


# ============================================================
# prazo_indeterminado NÃO bloqueia o cálculo de reajuste (Fluxo B) —
# deliberado, ver comentário em processar_calculo_reajuste. Renovação e
# correção monetária são decisões independentes; um contrato como o do
# Elias (renovado por inércia) continua com aluguel vigente sujeito ao
# índice pactuado, ano a ano.
# ============================================================


def test_calculo_reajuste_dispara_normalmente_em_prazo_indeterminado():
    """Caso Elias: prazo_indeterminado=true não deve impedir o alerta D-30
    de ser calculado e registrado — só a APLICAÇÃO em contracts.valor_aluguel
    é que sempre depende de decisao_gestora confirmada (ver
    _aplicar_reajustes_confirmados), com ou sem prazo indeterminado.

    processar_calculo_reajuste não olha data_termino (só faz sentido pro
    dispatcher de renovação, testado acima) — a janela D-30 aqui é
    calculada a partir do aniversário de data_inicio. Por isso hoje é
    derivado do próprio aniversário (10/03 - 30 dias), em vez de reusar a
    constante HOJE do topo do arquivo, que é 10/03/2026 e não cai na
    janela para data_inicio=10/03/2020 (diferença seria 0 dias, não 30)."""
    data_inicio = date(2020, 3, 10)
    aniversario_2026 = date(2026, 3, 10)
    hoje_na_janela_d30 = aniversario_2026 - timedelta(days=30)

    contrato = _contrato(
        tipo_renovacao="indeterminado_por_lei",
        prazo_indeterminado=True,
        indice_reajuste="igpm",
        data_inicio=data_inicio,
        data_termino=hoje_na_janela_d30,
    )

    chamado = {"buscar_percentual": False, "registrado": False}

    def buscar_percentual_fn(_indice):
        chamado["buscar_percentual"] = True
        return 5.0

    def registrar_calculo_reajuste_fn(*_args):
        chamado["registrado"] = True
        return True

    resultado = processar_calculo_reajuste(
        contrato,
        hoje_na_janela_d30,
        buscar_percentual_fn=buscar_percentual_fn,
        registrar_calculo_reajuste_fn=registrar_calculo_reajuste_fn,
        listar_clausulas_fn=lambda *_args: [],
    )

    assert resultado is not None
    assert chamado["buscar_percentual"] is True
    assert chamado["registrado"] is True


def test_calculo_reajuste_pula_indice_sem_calculo_automatico():
    """Guard já existente, sem relação com prazo_indeterminado — cobre
    livre_negociacao (ou indice_reajuste=None), que nunca deve calcular
    reajuste automático."""
    contrato = _contrato(indice_reajuste="livre_negociacao", data_termino=HOJE)

    chamado = {"buscar_percentual": False}

    def buscar_percentual_fn(_indice):
        chamado["buscar_percentual"] = True
        return 5.0

    resultado = processar_calculo_reajuste(
        contrato,
        HOJE,
        buscar_percentual_fn=buscar_percentual_fn,
        registrar_calculo_reajuste_fn=lambda *_args: True,
        listar_clausulas_fn=lambda *_args: [],
    )

    assert resultado is None
    assert chamado["buscar_percentual"] is False