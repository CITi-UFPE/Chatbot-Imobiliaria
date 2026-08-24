"""Testes do transporte WhatsApp do A4 (WA-09) — separação entre gerar/
registrar o alerta (já coberto em test_a4_fluxo.py) e transportá-lo.
Nenhum destes testes acessa a Meta de verdade: ou o kill switch está
desligado (modo simulado real do whatsapp_client), ou whatsapp_client.
enviar_template é substituído por um fake via monkeypatch."""

from datetime import date
from unittest.mock import patch
from uuid import UUID

import pytest

from app.agents.a4_gestao_contratual import fluxo
from app.models.contract_alerts import ContratoParaAlerta
from app.tools import whatsapp_client as wc

CONTRACT_ID = UUID("22222222-2222-2222-2222-222222222222")


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


# ======================================================================
# _notificar_staff_alerta_contratual — unidade
# ======================================================================


def test_notificar_staff_simulado_nao_exige_telefone_nem_faz_rede(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "false")
    monkeypatch.delenv("WHATSAPP_STAFF_PHONE_NUMBER", raising=False)

    resultado = fluxo._notificar_staff_alerta_contratual("Reajuste de aluguel", "corpo qualquer")

    assert resultado is None


def test_notificar_staff_ativo_sem_telefone_levanta_erro(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
    monkeypatch.delenv("WHATSAPP_STAFF_PHONE_NUMBER", raising=False)

    with pytest.raises(RuntimeError, match="WHATSAPP_STAFF_PHONE_NUMBER"):
        fluxo._notificar_staff_alerta_contratual("Reajuste de aluguel", "corpo qualquer")


def test_notificar_staff_ativo_envia_template_com_parametros_corretos(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
    monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")

    chamadas = []

    def fake_enviar_template(telefone, nome, parametros, lang="pt_BR"):
        chamadas.append((telefone, nome, parametros))
        return wc.ResultadoEnvio(sucesso=True, simulado=False, message_id="wamid.STAFF1")

    monkeypatch.setattr(wc, "enviar_template", fake_enviar_template)

    resultado = fluxo._notificar_staff_alerta_contratual("Reajuste de aluguel", "corpo da mensagem")

    assert resultado == "wamid.STAFF1"
    assert chamadas == [
        ("+5581988887777", "alerta_contratual", ["Reajuste de aluguel", "corpo da mensagem"])
    ]


def test_notificar_staff_propaga_falha_de_transporte(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
    monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")

    def enviar_template_com_falha(*args, **kwargs):
        raise wc.WhatsAppTransientError("Meta fora do ar")

    monkeypatch.setattr(wc, "enviar_template", enviar_template_com_falha)

    with pytest.raises(wc.WhatsAppTransientError):
        fluxo._notificar_staff_alerta_contratual("Reajuste de aluguel", "corpo qualquer")


# ======================================================================
# processar_alerta_renovacao — integração com o transporte (renovação)
# ======================================================================


def test_processar_alerta_renovacao_chama_notificacao_com_label_correto():
    contrato = _contrato(data_inicio=date(2025, 9, 13), data_termino=date(2026, 9, 13))
    registrar = RegistroChamadas(retorno=True)
    notificacoes = []

    def fake_notificar(tipo_label, mensagem):
        notificacoes.append((tipo_label, mensagem))
        return "wamid.X"

    resultado = fluxo.processar_alerta_renovacao(
        contrato,
        date(2026, 7, 15),
        registrar_alerta_renovacao_fn=registrar,
        enviar_notificacao_fn=fake_notificar,
    )

    assert resultado is not None
    assert notificacoes == [("Renovação de contrato", resultado)]


def test_processar_alerta_renovacao_falha_no_envio_propaga_sem_desfazer_registro():
    contrato = _contrato(data_inicio=date(2025, 9, 13), data_termino=date(2026, 9, 13))
    registrar = RegistroChamadas(retorno=True)

    def notificar_com_falha(tipo_label, mensagem):
        raise RuntimeError("Meta fora do ar")

    with pytest.raises(RuntimeError, match="Meta fora do ar"):
        fluxo.processar_alerta_renovacao(
            contrato,
            date(2026, 7, 15),
            registrar_alerta_renovacao_fn=registrar,
            enviar_notificacao_fn=notificar_com_falha,
        )

    # O registro do alerta de negócio já aconteceu e NÃO é desfeito pela
    # falha de transporte — separação explícita da WA-09.
    assert registrar.chamadas == [(CONTRACT_ID, date(2026, 7, 15))]


def test_processar_alerta_renovacao_sem_notificacao_injetada_usa_padrao_simulado(monkeypatch):
    """Regressão de compatibilidade: os testes já existentes de
    processar_alerta_renovacao (test_a4_fluxo.py) não passam
    enviar_notificacao_fn — precisam continuar funcionando sem exigir
    nenhuma configuração de WhatsApp."""
    monkeypatch.delenv("WHATSAPP_ENVIO_ATIVO", raising=False)
    monkeypatch.delenv("WHATSAPP_STAFF_PHONE_NUMBER", raising=False)
    contrato = _contrato(data_inicio=date(2025, 9, 13), data_termino=date(2026, 9, 13))
    registrar = RegistroChamadas(retorno=True)

    resultado = fluxo.processar_alerta_renovacao(
        contrato, date(2026, 7, 15), registrar_alerta_renovacao_fn=registrar
    )

    assert resultado is not None


# ======================================================================
# processar_calculo_reajuste — integração com o transporte (reajuste)
# ======================================================================


def test_processar_calculo_reajuste_chama_notificacao_com_label_correto():
    contrato = _contrato(data_inicio=date(2020, 8, 14), valor_aluguel=1500.0, indice_reajuste="igpm")
    notificacoes = []

    def fake_notificar(tipo_label, mensagem):
        notificacoes.append((tipo_label, mensagem))
        return "wamid.Y"

    resultado = fluxo.processar_calculo_reajuste(
        contrato,
        date(2026, 7, 15),
        buscar_percentual_fn=RegistroChamadas(retorno=3.18),
        registrar_calculo_reajuste_fn=RegistroChamadas(retorno=True),
        listar_clausulas_fn=RegistroChamadas(retorno=[("5.2", "Reajuste anual pelo IGPM.")]),
        enviar_notificacao_fn=fake_notificar,
    )

    assert resultado is not None
    assert notificacoes == [("Reajuste de aluguel", resultado)]


def test_processar_calculo_reajuste_falha_no_envio_propaga_sem_desfazer_registro():
    contrato = _contrato(data_inicio=date(2020, 8, 14), valor_aluguel=1500.0, indice_reajuste="igpm")
    registrar = RegistroChamadas(retorno=True)

    def notificar_com_falha(tipo_label, mensagem):
        raise RuntimeError("Meta fora do ar")

    with pytest.raises(RuntimeError, match="Meta fora do ar"):
        fluxo.processar_calculo_reajuste(
            contrato,
            date(2026, 7, 15),
            buscar_percentual_fn=RegistroChamadas(retorno=3.18),
            registrar_calculo_reajuste_fn=registrar,
            listar_clausulas_fn=RegistroChamadas(retorno=[]),
            enviar_notificacao_fn=notificar_com_falha,
        )

    assert registrar.chamadas


# ======================================================================
# executar_alertas_contratuais — ponta a ponta (registro isolado da falha
# de transporte, e modo simulado não impede o alerta de aparecer no
# resultado estruturado do cron)
# ======================================================================


class TestExecutarAlertasContratuaisComTransporte:
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_reajustes_para_aplicar")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_clausulas_financeiras")
    @patch("app.agents.a4_gestao_contratual.fluxo.registrar_calculo_reajuste")
    @patch("app.agents.a4_gestao_contratual.fluxo.buscar_percentual_acumulado_12_meses")
    @patch("app.agents.a4_gestao_contratual.fluxo.registrar_alerta_renovacao")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_contratos_ativos")
    def test_notificacao_simulada_nao_impede_alerta_de_aparecer_no_resultado(
        self,
        mock_listar_contratos,
        mock_registrar_alerta,
        mock_buscar_percentual,
        mock_registrar_reajuste,
        mock_listar_clausulas,
        mock_listar_reajustes_aplicar,
        monkeypatch,
    ):
        monkeypatch.delenv("WHATSAPP_ENVIO_ATIVO", raising=False)  # kill switch desligado (padrão)
        contrato = _contrato(data_termino=date(2026, 9, 13))
        mock_listar_contratos.return_value = [contrato]
        mock_registrar_alerta.return_value = True
        mock_buscar_percentual.return_value = 3.0
        mock_registrar_reajuste.return_value = False  # sem cálculo de reajuste nesse fixture
        mock_listar_clausulas.return_value = []
        mock_listar_reajustes_aplicar.return_value = []

        resultado = fluxo.executar_alertas_contratuais(hoje=date(2026, 7, 15))

        assert len(resultado.alertas_renovacao) == 1
        assert resultado.erros == []

    @patch("app.agents.a4_gestao_contratual.fluxo.listar_reajustes_para_aplicar")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_clausulas_financeiras")
    @patch("app.agents.a4_gestao_contratual.fluxo.registrar_calculo_reajuste")
    @patch("app.agents.a4_gestao_contratual.fluxo.buscar_percentual_acumulado_12_meses")
    @patch("app.agents.a4_gestao_contratual.fluxo.registrar_alerta_renovacao")
    @patch("app.agents.a4_gestao_contratual.fluxo.listar_contratos_ativos")
    def test_falha_no_transporte_vira_erro_sem_apagar_o_registro(
        self,
        mock_listar_contratos,
        mock_registrar_alerta,
        mock_buscar_percentual,
        mock_registrar_reajuste,
        mock_listar_clausulas,
        mock_listar_reajustes_aplicar,
        monkeypatch,
    ):
        monkeypatch.setenv("WHATSAPP_ENVIO_ATIVO", "true")
        monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")

        def enviar_template_com_falha(*args, **kwargs):
            raise wc.WhatsAppTransientError("Meta fora do ar")

        monkeypatch.setattr(wc, "enviar_template", enviar_template_com_falha)

        contrato = _contrato(data_termino=date(2026, 9, 13))
        mock_listar_contratos.return_value = [contrato]
        mock_registrar_alerta.return_value = True
        mock_buscar_percentual.return_value = 3.0
        mock_registrar_reajuste.return_value = False  # sem cálculo de reajuste nesse fixture
        mock_listar_clausulas.return_value = []
        mock_listar_reajustes_aplicar.return_value = []

        resultado = fluxo.executar_alertas_contratuais(hoje=date(2026, 7, 15))

        # A alerta não entra na lista "gerado com sucesso" desta execução
        # (a falha propagou antes do return), mas o registro no banco (a
        # linha abaixo) já tinha acontecido e não foi desfeito.
        assert resultado.alertas_renovacao == []
        assert len(resultado.erros) == 1
        assert "Meta fora do ar" in resultado.erros[0]
        mock_registrar_alerta.assert_called_once()
