from datetime import date, datetime
from unittest.mock import patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.agents.a4_gestao_contratual.fluxo import (
    _hoje_no_fuso_do_projeto,
    executar_alertas_contratuais,
    processar_alerta_renovacao,
    processar_calculo_reajuste,
    processar_finalizacao_contrato,
)
from app.models.contract_alerts import ContratoParaAlerta

CONTRACT_ID = UUID("11111111-1111-1111-1111-111111111111")


def _contrato(**overrides) -> ContratoParaAlerta:
    base = {
        "id": CONTRACT_ID,
        "imovel_identificacao": "Apto 302, Ed. X",
        "inquilino_nome": "João Silva",
        "telefone_whatsapp": "+5581999999999",
        "data_inicio": date(2025, 8, 14),
        "data_termino": date(2026, 9, 13),
        "indice_reajuste": "igpm",
        "valor_aluguel": 1500.0,
    }
    base.update(overrides)
    return ContratoParaAlerta(**base)


class RegistroChamadas:
    def __init__(self, retorno=True):
        self.chamadas = []
        self.retorno = retorno

    def __call__(self, *args):
        self.chamadas.append(args)
        return self.retorno


class TestProcessarAlertaRenovacao:
    def test_fora_da_janela_nao_faz_nada(self):
        contrato = _contrato(data_termino=date(2026, 12, 1))
        registrar = RegistroChamadas()

        resultado = processar_alerta_renovacao(
            contrato, date(2026, 7, 15), registrar_alerta_renovacao_fn=registrar
        )

        assert resultado is None
        assert not registrar.chamadas

    def test_na_janela_registra_e_monta_mensagem(self):
        contrato = _contrato(
            data_inicio=date(2025, 9, 13), data_termino=date(2026, 9, 13), imovel_identificacao="Apto 302, Ed. X"
        )
        registrar = RegistroChamadas(retorno=True)

        resultado = processar_alerta_renovacao(
            contrato, date(2026, 7, 15), registrar_alerta_renovacao_fn=registrar
        )

        assert resultado is not None
        assert "Apto 302, Ed. X" in resultado
        assert "12 meses" in resultado
        assert registrar.chamadas == [(CONTRACT_ID, date(2026, 7, 15))]

    def test_ja_disparado_hoje_nao_remonta_mensagem(self):
        contrato = _contrato(data_inicio=date(2025, 9, 13), data_termino=date(2026, 9, 13))
        registrar = RegistroChamadas(retorno=False)

        resultado = processar_alerta_renovacao(
            contrato, date(2026, 7, 15), registrar_alerta_renovacao_fn=registrar
        )

        assert resultado is None

    def test_prazo_indeterminado_nunca_dispara_alerta_mesmo_na_janela(self):
        """Contrato de prazo indeterminado (Migration 013) — data_termino é só
        um valor histórico, não deve gerar alerta de renovação mesmo que
        coincida com a janela D-60 (regressão)."""
        contrato = _contrato(
            data_inicio=date(2025, 9, 13), data_termino=date(2026, 9, 13), prazo_indeterminado=True
        )
        registrar = RegistroChamadas()

        resultado = processar_alerta_renovacao(
            contrato, date(2026, 7, 15), registrar_alerta_renovacao_fn=registrar
        )

        assert resultado is None
        assert not registrar.chamadas


class TestProcessarFinalizacaoContrato:
    def test_fora_da_data_termino_nao_finaliza(self):
        contrato = _contrato(data_termino=date(2026, 9, 13))
        finalizar = RegistroChamadas()

        resultado = processar_finalizacao_contrato(
            contrato, date(2026, 7, 15), finalizar_contrato_fn=finalizar
        )

        assert resultado is None
        assert not finalizar.chamadas

    def test_na_data_termino_finaliza(self):
        contrato = _contrato(data_termino=date(2026, 7, 15))
        finalizar = RegistroChamadas(retorno=True)

        resultado = processar_finalizacao_contrato(
            contrato, date(2026, 7, 15), finalizar_contrato_fn=finalizar
        )

        assert resultado == CONTRACT_ID
        assert finalizar.chamadas == [(CONTRACT_ID,)]

    def test_finalizar_contrato_fn_retorna_false_sem_excecao(self):
        """Já não estava mais 'ativo' (outra chamada já finalizou) — não é
        erro, só devolve None sem propagar."""
        contrato = _contrato(data_termino=date(2026, 7, 15))
        finalizar = RegistroChamadas(retorno=False)

        resultado = processar_finalizacao_contrato(
            contrato, date(2026, 7, 15), finalizar_contrato_fn=finalizar
        )

        assert resultado is None

    def test_prazo_indeterminado_nunca_finaliza_mesmo_na_data_termino(self):
        """Regressão do bug encontrado: a finalização automática (Migration
        012) não checava prazo_indeterminado (Migration 013) — um contrato
        de prazo indeterminado cujo data_termino "decorativo" coincidisse
        com hoje seria desativado por engano. data_termino aqui NUNCA é uma
        data real de encerramento para esses contratos."""
        contrato = _contrato(data_termino=date(2026, 7, 15), prazo_indeterminado=True)
        finalizar = RegistroChamadas(retorno=True)

        resultado = processar_finalizacao_contrato(
            contrato, date(2026, 7, 15), finalizar_contrato_fn=finalizar
        )

        assert resultado is None
        assert not finalizar.chamadas


class TestProcessarCalculoReajuste:
    def test_livre_negociacao_nao_calcula(self):
        contrato = _contrato(indice_reajuste="livre_negociacao")
        buscar_percentual = RegistroChamadas(retorno=3.0)

        resultado = processar_calculo_reajuste(
            contrato,
            date(2026, 7, 15),
            buscar_percentual_fn=buscar_percentual,
            registrar_calculo_reajuste_fn=RegistroChamadas(retorno=True),
            listar_clausulas_fn=RegistroChamadas(retorno=[]),
        )

        assert resultado is None
        assert not buscar_percentual.chamadas

    def test_fora_da_janela_nao_busca_indice(self):
        contrato = _contrato(data_inicio=date(2020, 1, 1))
        buscar_percentual = RegistroChamadas(retorno=3.0)

        resultado = processar_calculo_reajuste(
            contrato,
            date(2026, 7, 15),
            buscar_percentual_fn=buscar_percentual,
            registrar_calculo_reajuste_fn=RegistroChamadas(retorno=True),
            listar_clausulas_fn=RegistroChamadas(retorno=[]),
        )

        assert resultado is None
        assert not buscar_percentual.chamadas

    def test_na_janela_calcula_registra_e_monta_mensagem(self):
        # aniversário 2026-08-14 (data_inicio=2020-08-14), hoje = 30 dias antes
        contrato = _contrato(data_inicio=date(2020, 8, 14), valor_aluguel=1500.0, indice_reajuste="igpm")
        buscar_percentual = RegistroChamadas(retorno=3.18)
        registrar = RegistroChamadas(retorno=True)
        listar_clausulas = RegistroChamadas(retorno=[("5.2", "Reajuste anual pelo IGPM.")])

        resultado = processar_calculo_reajuste(
            contrato,
            date(2026, 7, 15),
            buscar_percentual_fn=buscar_percentual,
            registrar_calculo_reajuste_fn=registrar,
            listar_clausulas_fn=listar_clausulas,
        )

        assert resultado is not None
        assert "IGPM" in resultado
        assert "5.2" in resultado
        assert "1.500,00" in resultado
        assert "1.547,70" in resultado
        assert buscar_percentual.chamadas == [("igpm",)]
        assert registrar.chamadas == [(CONTRACT_ID, date(2026, 7, 15), 3.18, 1547.7)]

    def test_ja_disparado_hoje_descarta_mensagem_ja_montada(self):
        """A mensagem é montada ANTES de registrar (evita perder o alerta se
        o registro suceder mas o resto da montagem falhar depois — ver
        comentário em processar_calculo_reajuste) — então a cláusula É
        buscada mesmo quando o resultado acaba descartado por já ter sido
        disparado hoje. Isso é uma troca deliberada: um pouco de trabalho a
        mais no caso raro de reexecução no mesmo dia, para nunca perder o
        alerta de um ano inteiro."""
        contrato = _contrato(data_inicio=date(2020, 8, 14), indice_reajuste="igpm")
        buscar_percentual = RegistroChamadas(retorno=3.18)
        registrar = RegistroChamadas(retorno=False)
        listar_clausulas = RegistroChamadas(retorno=[])

        resultado = processar_calculo_reajuste(
            contrato,
            date(2026, 7, 15),
            buscar_percentual_fn=buscar_percentual,
            registrar_calculo_reajuste_fn=registrar,
            listar_clausulas_fn=listar_clausulas,
        )

        assert resultado is None
        assert listar_clausulas.chamadas


class TestExecutarAlertasContratuais:
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_reajustes_para_aplicar")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_clausulas_financeiras")
    @patch("app.agents.a4_gestao_contratual.fluxo.registrar_calculo_reajuste")
    @patch("app.agents.a4_gestao_contratual.fluxo.buscar_percentual_acumulado_12_meses")
    @patch("app.agents.a4_gestao_contratual.fluxo.registrar_alerta_renovacao")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_contratos_ativos")
    def test_processa_lote_de_contratos_e_isola_erro_por_contrato(
        self,
        mock_listar_contratos,
        mock_registrar_alerta,
        mock_buscar_percentual,
        mock_registrar_reajuste,
        mock_listar_clausulas,
        mock_listar_reajustes_aplicar,
    ):
        contrato_ok = _contrato(id=CONTRACT_ID, data_termino=date(2026, 9, 13))
        contrato_com_erro = _contrato(id=uuid4(), data_termino=date(2026, 9, 13))
        mock_listar_contratos.return_value = [contrato_ok, contrato_com_erro]

        def registrar_alerta_side_effect(contract_id, data_disparo):
            if contract_id == contrato_com_erro.id:
                raise RuntimeError("falha simulada")
            return True

        mock_registrar_alerta.side_effect = registrar_alerta_side_effect
        mock_buscar_percentual.return_value = 3.0
        mock_registrar_reajuste.return_value = False  # sem cálculo de reajuste nesses fixtures
        mock_listar_clausulas.return_value = []
        mock_listar_reajustes_aplicar.return_value = []

        resultado = executar_alertas_contratuais(hoje=date(2026, 7, 15))

        assert len(resultado.alertas_renovacao) == 1
        assert len(resultado.erros) == 1
        assert str(contrato_com_erro.id) in resultado.erros[0]

    @patch("app.agents.a4_gestao_contratual.fluxo.aplicar_reajuste")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_reajustes_para_aplicar")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_contratos_ativos")
    def test_aplica_reajustes_confirmados_no_aniversario(
        self, mock_listar_contratos, mock_listar_reajustes_aplicar, mock_aplicar
    ):
        mock_listar_contratos.return_value = []
        alerta_id = uuid4()
        mock_listar_reajustes_aplicar.return_value = [
            {"alerta_id": alerta_id, "contract_id": CONTRACT_ID, "valor_sugerido": 1547.7}
        ]
        mock_aplicar.return_value = True

        resultado = executar_alertas_contratuais(hoje=date(2026, 8, 14))

        mock_aplicar.assert_called_once_with(alerta_id, CONTRACT_ID, 1547.7)
        assert resultado.reajustes_aplicados == [alerta_id]

    @patch("app.agents.a4_gestao_contratual.fluxo.aplicar_reajuste")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_reajustes_para_aplicar")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_contratos_ativos")
    def test_aplicacao_de_reajuste_isola_erro_por_item(
        self, mock_listar_contratos, mock_listar_reajustes_aplicar, mock_aplicar
    ):
        """1 item falhando não pode derrubar os demais nem descartar os que
        já foram aplicados com sucesso antes dele (regressão)."""
        mock_listar_contratos.return_value = []
        alerta_ok_1, alerta_com_erro, alerta_ok_2 = uuid4(), uuid4(), uuid4()
        mock_listar_reajustes_aplicar.return_value = [
            {"alerta_id": alerta_ok_1, "contract_id": CONTRACT_ID, "valor_sugerido": 1500.0},
            {"alerta_id": alerta_com_erro, "contract_id": CONTRACT_ID, "valor_sugerido": 1600.0},
            {"alerta_id": alerta_ok_2, "contract_id": CONTRACT_ID, "valor_sugerido": 1700.0},
        ]

        def aplicar_side_effect(alerta_id, contract_id, valor_aplicado):
            if alerta_id == alerta_com_erro:
                raise RuntimeError("falha simulada")
            return True

        mock_aplicar.side_effect = aplicar_side_effect

        resultado = executar_alertas_contratuais(hoje=date(2026, 8, 14))

        assert resultado.reajustes_aplicados == [alerta_ok_1, alerta_ok_2]
        assert len(resultado.erros) == 1
        assert str(alerta_com_erro) in resultado.erros[0]

    @patch("app.agents.a4_gestao_contratual.fluxo.aplicar_reajuste")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_reajustes_para_aplicar")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_contratos_ativos")
    def test_aplicacao_retorna_false_sem_excecao_vira_erro_registrado(
        self, mock_listar_contratos, mock_listar_reajustes_aplicar, mock_aplicar
    ):
        """aplicar_reajuste pode devolver False sem lançar exceção (condição
        não bateu mais no momento da escrita) — isso não pode ser tratado
        como sucesso silencioso nem ser descartado sem deixar rastro."""
        mock_listar_contratos.return_value = []
        alerta_id = uuid4()
        mock_listar_reajustes_aplicar.return_value = [
            {"alerta_id": alerta_id, "contract_id": CONTRACT_ID, "valor_sugerido": 1547.7}
        ]
        mock_aplicar.return_value = False

        resultado = executar_alertas_contratuais(hoje=date(2026, 8, 14))

        assert resultado.reajustes_aplicados == []
        assert len(resultado.erros) == 1
        assert str(alerta_id) in resultado.erros[0]


class TestHojeNoFusoDoProjeto:
    def test_usa_fuso_america_recife_por_padrao(self, monkeypatch):
        monkeypatch.delenv("TIMEZONE", raising=False)
        esperado = datetime.now(ZoneInfo("America/Recife")).date()

        assert _hoje_no_fuso_do_projeto() == esperado

    def test_respeita_timezone_do_ambiente(self, monkeypatch):
        monkeypatch.setenv("TIMEZONE", "UTC")
        esperado = datetime.now(ZoneInfo("UTC")).date()

        assert _hoje_no_fuso_do_projeto() == esperado
