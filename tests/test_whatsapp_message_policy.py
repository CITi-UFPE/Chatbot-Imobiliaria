"""WA-08 — política central de texto/template e templates do cron A2."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agents.a2_cobranca.mensagens import montar_template_cobranca
from app.agents.a2_cobranca.schemas import ChargeAtiva, DadosCobrancaContrato
from app.tools import whatsapp_message_policy as policy

AGORA = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
TEXTO = "Resposta livre do agente."
FALLBACK = policy.TEMPLATE_RETOMADA_ATENDIMENTO


class _ClientUltimaMensagem:
    def __init__(self, data=None, erro: Exception | None = None):
        self.data = data
        self.erro = erro
        self.chamadas: list[tuple[str, dict]] = []

    def rpc(self, nome: str, parametros: dict):
        self.chamadas.append((nome, parametros))
        return self

    def execute(self):
        if self.erro:
            raise self.erro
        return MagicMock(data=self.data)


def _decidir_com_idade(idade: timedelta):
    return policy.decidir_saida(
        reativa=True,
        texto=TEXTO,
        template=FALLBACK,
        ultima_mensagem_inquilino=AGORA - idade,
        agora=AGORA,
    )


def test_23h59_permite_texto_livre_reativo():
    saida = _decidir_com_idade(timedelta(hours=23, minutes=59))

    assert isinstance(saida, policy.MensagemTexto)
    assert saida.texto == TEXTO


def test_24h_exatas_exigem_template():
    saida = _decidir_com_idade(timedelta(hours=24))

    assert saida == FALLBACK


def test_mais_de_24h_exige_template():
    saida = _decidir_com_idade(timedelta(hours=24, seconds=1))

    assert saida == FALLBACK


def test_ausencia_de_historico_exige_template():
    client = _ClientUltimaMensagem(data=None)

    saida = policy.decidir_saida_para_contrato(
        client,
        reativa=True,
        texto=TEXTO,
        template=FALLBACK,
        agora=AGORA,
    )

    assert saida == FALLBACK
    assert client.chamadas == [("agent_get_last_tenant_message_at", {})]


def test_falha_de_banco_exige_template(caplog):
    client = _ClientUltimaMensagem(erro=RuntimeError("Supabase indisponível"))

    with caplog.at_level("ERROR"):
        saida = policy.decidir_saida_para_contrato(
            client,
            reativa=True,
            texto=TEXTO,
            template=FALLBACK,
            agora=AGORA,
        )

    assert saida == FALLBACK
    assert "usando template por segurança" in caplog.text


def test_timestamp_sem_timezone_exige_template():
    client = _ClientUltimaMensagem(data="2026-08-25T11:00:00")

    saida = policy.decidir_saida_para_contrato(
        client,
        reativa=True,
        texto=TEXTO,
        template=FALLBACK,
        agora=AGORA,
    )

    assert saida == FALLBACK


def test_timestamp_futuro_exige_template():
    saida = policy.decidir_saida(
        reativa=True,
        texto=TEXTO,
        template=FALLBACK,
        ultima_mensagem_inquilino=AGORA + timedelta(seconds=1),
        agora=AGORA,
    )

    assert saida == FALLBACK


def test_proativo_usa_template_sem_consultar_banco():
    client = _ClientUltimaMensagem(erro=AssertionError("não deveria consultar"))
    template = policy.MensagemTemplate(nome="aviso_vencimento", parametros=("João",))

    saida = policy.decidir_saida_para_contrato(
        client,
        reativa=False,
        texto="não deve sair",
        template=template,
        agora=AGORA,
    )

    assert saida == template
    assert client.chamadas == []


def test_busca_normaliza_timestamp_com_offset_para_utc():
    client = _ClientUltimaMensagem(data="2026-08-25T09:00:00-03:00")

    ultima = policy.buscar_ultima_mensagem_inquilino(client)

    assert ultima == AGORA
    assert ultima.tzinfo == timezone.utc


@pytest.fixture
def dados_cobranca() -> DadosCobrancaContrato:
    return DadosCobrancaContrato(
        telefone_whatsapp="+5581999990000",
        inquilino_nome="João Pereira",
        imovel_identificacao="Apto 305, Ed. Girassol",
        multa_moratoria_percentual=0.02,
        juros_moratorio_mensal=0.01,
    )


def _charge(*, tipo: str = "aluguel", dias_atraso: int = 5) -> ChargeAtiva:
    vencimento = date(2026, 8, 20)
    return ChargeAtiva(
        contract_id="11111111-1111-1111-1111-111111111111",
        charge_id="charge-1",
        tipo=tipo,
        mes_referencia=date(2026, 8, 1),
        valor_esperado=1500.0,
        data_vencimento=vencimento,
        dias_atraso=dias_atraso,
        status="atrasado" if dias_atraso > 0 else "pendente",
    )


@pytest.mark.parametrize(
    ("estagio", "dias_atraso", "nome_template"),
    [
        ("d-5", -5, "aviso_vencimento"),
        ("d0", 0, "aviso_vencimento"),
        ("d+5", 5, "aviso_atraso"),
        ("d+10", 10, "aviso_atraso"),
        ("d+15", 15, "aviso_atraso_severo"),
    ],
)
def test_mapeamento_de_todos_os_estagios_a2(
    dados_cobranca, estagio, dias_atraso, nome_template
):
    template = montar_template_cobranca(
        _charge(dias_atraso=dias_atraso),
        dados_cobranca,
        estagio,
        dias_atraso,
    )

    assert template.nome == nome_template
    assert template.idioma == "pt_BR"


def test_parametros_aviso_vencimento_na_ordem_meta(dados_cobranca):
    template = montar_template_cobranca(_charge(dias_atraso=-5), dados_cobranca, "d-5", -5)

    assert template.parametros == (
        "João Pereira",
        "o aluguel do Apto 305, Ed. Girassol",
        "20/08/2026",
    )


def test_parametros_aviso_atraso_com_formatacao_deterministica(dados_cobranca):
    template = montar_template_cobranca(_charge(dias_atraso=5), dados_cobranca, "d+5", 5)

    assert template.parametros == (
        "João Pereira",
        "o aluguel do Apto 305, Ed. Girassol",
        "20/08/2026",
        "5",
        "1.500,00",
        "30,00",
        "2,50",
        "1.532,50",
    )


def test_parametros_aviso_atraso_severo_na_ordem_meta(dados_cobranca):
    template = montar_template_cobranca(_charge(dias_atraso=15), dados_cobranca, "d+15", 15)

    assert template.parametros == (
        "João Pereira",
        "o aluguel do Apto 305, Ed. Girassol",
        "20/08/2026",
        "15",
        "1.537,50",
    )


def test_descricao_de_conta_e_derivada_do_modelo(dados_cobranca):
    template = montar_template_cobranca(
        _charge(tipo="agua", dias_atraso=0),
        dados_cobranca,
        "d0",
        0,
    )

    assert template.parametros[1] == "sua conta de água"


def test_cron_a2_entrega_template_estruturado_ao_notificador(dados_cobranca):
    charge_raw = _charge(dias_atraso=5).model_dump(mode="json")
    enviados = []
    client_agente = MagicMock()

    def rpc(nome, parametros):
        builder = MagicMock()
        if nome == "buscar_dados_cobranca_contrato":
            builder.execute.return_value = MagicMock(data=dados_cobranca.model_dump())
        elif nome == "agent_update_charge_status":
            builder.execute.return_value = MagicMock(data=None)
        else:
            raise AssertionError(f"RPC inesperada: {nome}")
        return builder

    client_agente.rpc.side_effect = rpc

    with patch(
        "app.agents.a2_cobranca.cobranca.obter_client_agente",
        return_value=client_agente,
    ), patch(
        "app.agents.a2_cobranca.cobranca.enviar_mensagem_cobranca",
        side_effect=lambda telefone, mensagem: enviados.append((telefone, mensagem)),
    ):
        from app.agents.a2_cobranca.cobranca import _processar_charge

        _processar_charge(charge_raw, date(2026, 8, 25))

    assert len(enviados) == 1
    telefone, mensagem = enviados[0]
    assert telefone == dados_cobranca.telefone_whatsapp
    assert isinstance(mensagem, policy.MensagemTemplate)
    assert mensagem.nome == "aviso_atraso"
