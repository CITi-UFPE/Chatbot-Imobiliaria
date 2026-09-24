"""Geração automática das charges de aluguel (Migration 025).

Parte 1 testa só a regra de datas (função pura, sem banco nem mock).
Parte 2 (Task 3) testa a orquestração com clients Supabase fake — mesmo
padrão de tests/test_notificacao_falha_preserva_estado.py.
"""

from datetime import date
from unittest.mock import MagicMock, patch

from app.agents.a2_cobranca.geracao import CobrancaAGerar, calcular_cobrancas_a_gerar
from app.agents.a2_cobranca.schemas import ContratoFaturamento


def _contrato(**overrides) -> ContratoFaturamento:
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "dia_vencimento": 23,
        "vencimento_mes_referencia": "atual",
        "data_inicio": date(2026, 1, 1),
        "data_termino": date(2027, 12, 31),
        "prazo_indeterminado": False,
    }
    base.update(overrides)
    return ContratoFaturamento.model_validate(base)


class TestJanela:
    def test_vencimento_dentro_da_janela_gera(self):
        assert calcular_cobrancas_a_gerar(_contrato(), date(2026, 9, 13)) == [
            CobrancaAGerar(mes_referencia=date(2026, 9, 1), data_vencimento=date(2026, 9, 23))
        ]

    def test_vencimento_hoje_gera(self):
        assert calcular_cobrancas_a_gerar(_contrato(), date(2026, 9, 23)) == [
            CobrancaAGerar(mes_referencia=date(2026, 9, 1), data_vencimento=date(2026, 9, 23))
        ]

    def test_vencimento_um_dia_depois_da_janela_nao_gera(self):
        # hoje + 10 = 22/09; vencimento 23/09 fica fora
        assert calcular_cobrancas_a_gerar(_contrato(), date(2026, 9, 12)) == []

    def test_vencimento_ja_passou_nao_gera_retroativo(self):
        # 24/09: o de setembro já venceu, o de outubro (23/10) está a 29 dias
        assert calcular_cobrancas_a_gerar(_contrato(), date(2026, 9, 24)) == []

    def test_recupera_se_cron_ficou_parado(self):
        # cron parado de 13 a 20/09: rodando no dia 21, o vencimento de 23/09 ainda gera
        assert calcular_cobrancas_a_gerar(_contrato(), date(2026, 9, 21)) == [
            CobrancaAGerar(mes_referencia=date(2026, 9, 1), data_vencimento=date(2026, 9, 23))
        ]

    def test_vencimento_no_mes_seguinte(self):
        assert calcular_cobrancas_a_gerar(_contrato(dia_vencimento=3), date(2026, 9, 25)) == [
            CobrancaAGerar(mes_referencia=date(2026, 10, 1), data_vencimento=date(2026, 10, 3))
        ]

    def test_virada_de_ano(self):
        assert calcular_cobrancas_a_gerar(_contrato(dia_vencimento=5), date(2026, 12, 28)) == [
            CobrancaAGerar(mes_referencia=date(2027, 1, 1), data_vencimento=date(2027, 1, 5))
        ]


class TestFimDeMes:
    def test_dia_31_em_setembro_vence_dia_30(self):
        assert calcular_cobrancas_a_gerar(_contrato(dia_vencimento=31), date(2026, 9, 25)) == [
            CobrancaAGerar(mes_referencia=date(2026, 9, 1), data_vencimento=date(2026, 9, 30))
        ]

    def test_dia_31_em_fevereiro_vence_dia_28(self):
        assert calcular_cobrancas_a_gerar(_contrato(dia_vencimento=31), date(2027, 2, 20)) == [
            CobrancaAGerar(mes_referencia=date(2027, 2, 1), data_vencimento=date(2027, 2, 28))
        ]

    def test_fevereiro_bissexto(self):
        contrato = _contrato(dia_vencimento=30, data_termino=date(2029, 1, 1))
        assert calcular_cobrancas_a_gerar(contrato, date(2028, 2, 20)) == [
            CobrancaAGerar(mes_referencia=date(2028, 2, 1), data_vencimento=date(2028, 2, 29))
        ]


class TestMesReferenciaAnterior:
    def test_anterior_referencia_o_mes_de_uso(self):
        contrato = _contrato(dia_vencimento=10, vencimento_mes_referencia="anterior")
        assert calcular_cobrancas_a_gerar(contrato, date(2026, 10, 1)) == [
            CobrancaAGerar(mes_referencia=date(2026, 9, 1), data_vencimento=date(2026, 10, 10))
        ]

    def test_anterior_na_virada_de_ano(self):
        contrato = _contrato(dia_vencimento=10, vencimento_mes_referencia="anterior")
        assert calcular_cobrancas_a_gerar(contrato, date(2027, 1, 1)) == [
            CobrancaAGerar(mes_referencia=date(2026, 12, 1), data_vencimento=date(2027, 1, 10))
        ]


class TestVigencia:
    def test_contrato_que_ainda_nao_comecou_nao_gera(self):
        contrato = _contrato(data_inicio=date(2026, 10, 15))
        assert calcular_cobrancas_a_gerar(contrato, date(2026, 9, 20)) == []

    def test_mes_de_inicio_gera_valor_cheio(self):
        contrato = _contrato(data_inicio=date(2026, 9, 15))
        assert len(calcular_cobrancas_a_gerar(contrato, date(2026, 9, 20))) == 1

    def test_vencimento_antes_do_inicio_nao_gera(self):
        # 'atual', início 15/09, dia 10: em 01/09 o vencimento 10/09 está na
        # janela e o mes_referencia (set) já é o mês de início — mas vence
        # antes do inquilino entrar. Primeiro mês fica para lançamento manual.
        contrato = _contrato(dia_vencimento=10, data_inicio=date(2026, 9, 15))
        assert calcular_cobrancas_a_gerar(contrato, date(2026, 9, 1)) == []

    def test_vencimento_no_dia_do_inicio_gera(self):
        contrato = _contrato(dia_vencimento=10, data_inicio=date(2026, 9, 10))
        assert calcular_cobrancas_a_gerar(contrato, date(2026, 9, 1)) == [
            CobrancaAGerar(mes_referencia=date(2026, 9, 1), data_vencimento=date(2026, 9, 10))
        ]

    def test_primeira_charge_apos_inicio_e_a_do_mes_seguinte(self):
        contrato = _contrato(dia_vencimento=10, data_inicio=date(2026, 9, 15))
        assert calcular_cobrancas_a_gerar(contrato, date(2026, 10, 1)) == [
            CobrancaAGerar(mes_referencia=date(2026, 10, 1), data_vencimento=date(2026, 10, 10))
        ]

    def test_contrato_terminado_nao_gera(self):
        contrato = _contrato(data_inicio=date(2025, 9, 1), data_termino=date(2026, 8, 31))
        assert calcular_cobrancas_a_gerar(contrato, date(2026, 9, 20)) == []

    def test_mes_de_termino_ainda_gera(self):
        contrato = _contrato(data_inicio=date(2025, 9, 1), data_termino=date(2026, 9, 10))
        assert len(calcular_cobrancas_a_gerar(contrato, date(2026, 9, 20))) == 1

    def test_prazo_indeterminado_ignora_data_termino(self):
        contrato = _contrato(
            data_inicio=date(2022, 4, 18), data_termino=date(2024, 4, 17), prazo_indeterminado=True
        )
        assert len(calcular_cobrancas_a_gerar(contrato, date(2026, 9, 20))) == 1


# =============================================================================
# PARTE 2 — orquestração (clients Supabase fake)
# =============================================================================

HOJE = date(2026, 9, 13)
ID_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ID_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _contrato_raw(contract_id: str, dia_vencimento: int = 23) -> dict:
    return {
        "id": contract_id,
        "dia_vencimento": dia_vencimento,
        "vencimento_mes_referencia": "atual",
        "data_inicio": "2026-01-01",
        "data_termino": "2027-12-31",
        "prazo_indeterminado": False,
    }


def _client_cron_fake(contratos: list[dict]) -> MagicMock:
    client = MagicMock()

    def _rpc(nome_funcao: str, parametros: dict):
        assert nome_funcao == "cron_listar_contratos_para_faturamento"
        builder = MagicMock()
        builder.execute.return_value = MagicMock(data=contratos)
        return builder

    client.rpc.side_effect = _rpc
    return client


def _client_agente_fake(chamadas: list, retorno) -> MagicMock:
    client = MagicMock()

    def _rpc(nome_funcao: str, parametros: dict):
        assert nome_funcao == "agent_gerar_charge_aluguel"
        chamadas.append(parametros)
        builder = MagicMock()
        builder.execute.return_value = MagicMock(data=retorno)
        return builder

    client.rpc.side_effect = _rpc
    return client


class TestGerarChargesAluguel:
    def test_chama_rpc_de_insert_com_datas_calculadas(self):
        from app.agents.a2_cobranca.geracao import gerar_charges_aluguel

        chamadas: list = []
        with patch(
            "app.agents.a2_cobranca.geracao.obter_client_cron_batch",
            return_value=_client_cron_fake([_contrato_raw(ID_A)]),
        ), patch(
            "app.agents.a2_cobranca.geracao.obter_client_agente",
            return_value=_client_agente_fake(chamadas, retorno="charge-nova"),
        ) as obter_agente:
            geradas = gerar_charges_aluguel(hoje=HOJE)

        assert geradas == 1
        obter_agente.assert_called_once_with(ID_A)
        assert chamadas == [{"p_mes_referencia": "2026-09-01", "p_data_vencimento": "2026-09-23"}]

    def test_contrato_fora_da_janela_nem_assina_token(self):
        from app.agents.a2_cobranca.geracao import gerar_charges_aluguel

        with patch(
            "app.agents.a2_cobranca.geracao.obter_client_cron_batch",
            return_value=_client_cron_fake([_contrato_raw(ID_A, dia_vencimento=1)]),
        ), patch("app.agents.a2_cobranca.geracao.obter_client_agente") as obter_agente:
            geradas = gerar_charges_aluguel(hoje=HOJE)

        assert geradas == 0
        obter_agente.assert_not_called()

    def test_charge_ja_existente_nao_conta_como_gerada(self):
        from app.agents.a2_cobranca.geracao import gerar_charges_aluguel

        chamadas: list = []
        with patch(
            "app.agents.a2_cobranca.geracao.obter_client_cron_batch",
            return_value=_client_cron_fake([_contrato_raw(ID_A)]),
        ), patch(
            "app.agents.a2_cobranca.geracao.obter_client_agente",
            return_value=_client_agente_fake(chamadas, retorno=None),
        ):
            geradas = gerar_charges_aluguel(hoje=HOJE)

        assert geradas == 0
        assert len(chamadas) == 1

    def test_erro_em_um_contrato_nao_interrompe_os_demais(self):
        from app.agents.a2_cobranca.geracao import gerar_charges_aluguel

        chamadas: list = []
        client_ok = _client_agente_fake(chamadas, retorno="charge-nova")

        def _obter(contract_id):
            if contract_id == ID_A:
                raise RuntimeError("falha ao assinar token")
            return client_ok

        with patch(
            "app.agents.a2_cobranca.geracao.obter_client_cron_batch",
            return_value=_client_cron_fake([_contrato_raw(ID_A), _contrato_raw(ID_B)]),
        ), patch("app.agents.a2_cobranca.geracao.obter_client_agente", side_effect=_obter):
            geradas = gerar_charges_aluguel(hoje=HOJE)

        assert geradas == 1
        assert len(chamadas) == 1

    def test_payload_invalido_e_pulado(self):
        from app.agents.a2_cobranca.geracao import gerar_charges_aluguel

        invalido = _contrato_raw(ID_A)
        invalido["dia_vencimento"] = None
        chamadas: list = []
        with patch(
            "app.agents.a2_cobranca.geracao.obter_client_cron_batch",
            return_value=_client_cron_fake([invalido, _contrato_raw(ID_B)]),
        ), patch(
            "app.agents.a2_cobranca.geracao.obter_client_agente",
            return_value=_client_agente_fake(chamadas, retorno="charge-nova"),
        ):
            geradas = gerar_charges_aluguel(hoje=HOJE)

        assert geradas == 1

    def test_exportada_no_pacote(self):
        from app.agents.a2_cobranca import gerar_charges_aluguel as exportada
        from app.agents.a2_cobranca.geracao import gerar_charges_aluguel

        assert exportada is gerar_charges_aluguel
