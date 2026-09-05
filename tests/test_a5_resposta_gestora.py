"""Testes da resposta da gestora via reply nativo do WhatsApp (Migration 022).

Cobre três camadas, cada uma isolada por monkeypatch/mock, nenhuma acessando
Supabase, Anthropic ou a Meta de verdade:
  1. app/agents/a5_escalonamento/escalonamento.py::executar_escalonamento —
     persistência do wamid da notificação após o envio.
  2. app/agents/a5_escalonamento/resposta_gestora.py — as 4 funções novas
     (identificar_contrato_por_wamid, obter_escalonamento_aberto,
     compor_resposta_inquilino, marcar_resolvido).
  3. app/orchestrator/processar_mensagem.py — reconhecimento do telefone da
     staff e o fluxo completo de _processar_resposta_staff.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agents.a5_escalonamento import escalonamento as esc
from app.agents.a5_escalonamento import notificacao as notif_a5
from app.agents.a5_escalonamento import resposta_gestora as rg
from app.orchestrator import processar_mensagem as pm
from app.tools import whatsapp_client as wc

# ======================================================================
# executar_escalonamento — persistência do wamid (Migration 022)
# ======================================================================


class _FakeClientEscalonamento:
    def __init__(self):
        self.chamadas: list[tuple[str, dict]] = []

    def rpc(self, nome, params):
        self.chamadas.append((nome, params))
        return self

    def execute(self):
        ultimo_nome = self.chamadas[-1][0]
        if ultimo_nome == "agent_create_escalation":
            return MagicMock(data="ESC-2026-00001")
        return MagicMock(data=True)


def _avaliacao(**overrides) -> esc.AvaliacaoEscalonamento:
    base = {
        "motivo": "sem_clausula",
        "descricao": "Pode ter cachorro?",
        "resposta_para_inquilino": "Já encaminhei pra equipe, já te retorno.",
    }
    base.update(overrides)
    return esc.AvaliacaoEscalonamento(**base)


def test_executar_escalonamento_grava_wamid_quando_notificacao_e_enviada(monkeypatch):
    client = _FakeClientEscalonamento()
    monkeypatch.setattr(esc, "obter_client_agente", lambda contract_id: client)
    monkeypatch.setattr(esc, "notificar_staff_escalonamento", lambda *a: "wamid.NOTIF1")

    protocolo = esc.executar_escalonamento("contract-1", _avaliacao())

    assert protocolo == "ESC-2026-00001"
    assert (
        "agent_registrar_wamid_escalonamento",
        {"p_protocolo": "ESC-2026-00001", "p_wamid": "wamid.NOTIF1"},
    ) in client.chamadas


def test_executar_escalonamento_nao_grava_wamid_em_modo_simulado(monkeypatch):
    """notificar_staff_escalonamento devolve None em modo simulado (kill
    switch desligado) — sem wamid nenhum, não faz sentido chamar a RPC de
    registro."""
    client = _FakeClientEscalonamento()
    monkeypatch.setattr(esc, "obter_client_agente", lambda contract_id: client)
    monkeypatch.setattr(esc, "notificar_staff_escalonamento", lambda *a: None)

    esc.executar_escalonamento("contract-1", _avaliacao())

    nomes = [nome for nome, _ in client.chamadas]
    assert "agent_registrar_wamid_escalonamento" not in nomes


def test_executar_escalonamento_falha_ao_notificar_nao_impede_protocolo(monkeypatch):
    client = _FakeClientEscalonamento()
    monkeypatch.setattr(esc, "obter_client_agente", lambda contract_id: client)

    def _falha(*a):
        raise RuntimeError("Meta fora do ar")

    monkeypatch.setattr(esc, "notificar_staff_escalonamento", _falha)

    protocolo = esc.executar_escalonamento("contract-1", _avaliacao())

    assert protocolo == "ESC-2026-00001"  # a gravação da escalação em si não é afetada
    nomes = [nome for nome, _ in client.chamadas]
    assert "agent_registrar_wamid_escalonamento" not in nomes


def test_executar_escalonamento_falha_ao_gravar_wamid_nao_propaga(monkeypatch):
    class _ClientComFalhaNoRegistro(_FakeClientEscalonamento):
        def execute(self):
            ultimo_nome, _ = self.chamadas[-1]
            if ultimo_nome == "agent_registrar_wamid_escalonamento":
                raise RuntimeError("falha ao gravar wamid")
            return super().execute()

    client = _ClientComFalhaNoRegistro()
    monkeypatch.setattr(esc, "obter_client_agente", lambda contract_id: client)
    monkeypatch.setattr(esc, "notificar_staff_escalonamento", lambda *a: "wamid.NOTIF1")

    protocolo = esc.executar_escalonamento("contract-1", _avaliacao())  # não deve levantar

    assert protocolo == "ESC-2026-00001"


# ======================================================================
# resposta_gestora.py — funções isoladas
# ======================================================================


class _FakeClientAnon:
    def __init__(self, retorno):
        self.retorno = retorno
        self.chamadas: list[tuple[str, dict]] = []

    def rpc(self, nome, params):
        self.chamadas.append((nome, params))
        return self

    def execute(self):
        return MagicMock(data=self.retorno)


def test_identificar_contrato_por_wamid_chama_rpc_anon(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-anon-fake")

    fake_client = _FakeClientAnon("contract-1")
    monkeypatch.setattr(rg, "create_client", lambda url, key: fake_client)

    resultado = rg.identificar_contrato_por_wamid("wamid.NOTIF1")

    assert resultado == "contract-1"
    assert fake_client.chamadas == [
        ("resolver_escalonamento_por_wamid", {"p_wamid": "wamid.NOTIF1"})
    ]


def test_identificar_contrato_por_wamid_sem_configuracao_levanta_erro_claro(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        rg.identificar_contrato_por_wamid("wamid.NOTIF1")


def test_obter_escalonamento_aberto_chama_rpc_escopada():
    dados = {
        "protocolo": "ESC-2026-00001",
        "motivo": "sem_clausula",
        "descricao": "Pode ter cachorro?",
        "telefone_whatsapp": "+5581999998888",
    }
    client = _FakeClientAnon(dados)

    resultado = rg.obter_escalonamento_aberto(client, "wamid.NOTIF1")

    assert resultado == dados
    assert client.chamadas == [
        ("agent_obter_escalonamento_aberto_por_wamid", {"p_wamid": "wamid.NOTIF1"})
    ]


def test_obter_escalonamento_aberto_devolve_none_quando_nao_existe():
    client = _FakeClientAnon(None)

    assert rg.obter_escalonamento_aberto(client, "wamid.NOTIF1") is None


def test_marcar_resolvido_devolve_booleano_da_rpc():
    client_true = _FakeClientAnon(True)
    client_false = _FakeClientAnon(False)

    assert rg.marcar_resolvido(client_true, "ESC-2026-00001") is True
    assert rg.marcar_resolvido(client_false, "ESC-2026-00001") is False
    assert client_true.chamadas == [
        ("agent_marcar_escalonamento_resolvido", {"p_protocolo": "ESC-2026-00001"})
    ]


class TestComporRespostaInquilino:
    @patch("app.agents.a5_escalonamento.resposta_gestora.anthropic.Anthropic")
    def test_usa_pergunta_e_resposta_da_gestora_no_prompt(self, mock_anthropic_cls):
        mock_client = MagicMock()
        bloco = SimpleNamespace(type="text", text="Não, animais de estimação não são permitidos.")
        mock_client.messages.create.return_value = SimpleNamespace(content=[bloco])
        mock_anthropic_cls.return_value = mock_client

        resultado = rg.compor_resposta_inquilino("Posso ter cachorro?", "não")

        assert resultado == "Não, animais de estimação não são permitidos."
        _, kwargs = mock_client.messages.create.call_args
        texto_enviado = kwargs["messages"][0]["content"]
        assert "Posso ter cachorro?" in texto_enviado
        assert "não" in texto_enviado
        assert "Nunca" in kwargs["system"]  # guardrail contra alucinação presente no prompt

    @patch("app.agents.a5_escalonamento.resposta_gestora.anthropic.Anthropic")
    def test_sem_bloco_de_texto_levanta_erro(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(content=[])
        mock_anthropic_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="sem bloco de texto"):
            rg.compor_resposta_inquilino("Posso ter cachorro?", "não")


# ======================================================================
# processar_mensagem.py — reconhecimento do telefone da staff
# ======================================================================


class TestEhMensagemDaStaff:
    def test_reconhece_mesmo_telefone_com_formatacao_diferente(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+55 (81) 98888-7777")

        assert pm._eh_mensagem_da_staff("5581988887777") is True

    def test_nao_reconhece_telefone_diferente(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")

        assert pm._eh_mensagem_da_staff("5581999998888") is False

    def test_sem_variavel_configurada_nunca_reconhece_ninguem(self, monkeypatch):
        monkeypatch.delenv("WHATSAPP_STAFF_PHONE_NUMBER", raising=False)

        assert pm._eh_mensagem_da_staff("5581988887777") is False

    def test_reconhece_quando_staff_tem_nono_digito_e_remetente_nao(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")

        assert pm._eh_mensagem_da_staff("558188887777") is True

    def test_reconhece_quando_remetente_tem_nono_digito_e_staff_nao(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "558188887777")

        assert pm._eh_mensagem_da_staff("5581988887777") is True


# ======================================================================
# processar_mensagem.py — dispatch e _processar_resposta_staff
# ======================================================================


def _payload_reply_staff(
    telefone: str = "+5581988887777", texto: str = "não", wamid_respondido: str | None = "wamid.NOTIF1"
) -> dict:
    mensagem = {
        "id": "wamid.reply1",
        "from": telefone,
        "type": "text",
        "text": {"body": texto},
    }
    if wamid_respondido is not None:
        mensagem["context"] = {"id": wamid_respondido}
    return {"entry": [{"changes": [{"value": {"messages": [mensagem]}}]}]}


@pytest.fixture
def staff_configurada(monkeypatch):
    monkeypatch.setenv("WHATSAPP_STAFF_PHONE_NUMBER", "+5581988887777")


def test_dispatch_reconhece_staff_e_nao_cai_no_fluxo_de_inquilino(monkeypatch, staff_configurada):
    chamado_fluxo_inquilino = []
    monkeypatch.setattr(
        pm, "_resolver_contract_id", lambda tel: chamado_fluxo_inquilino.append(tel) or "contract-x"
    )
    monkeypatch.setattr(pm, "_processar_resposta_staff", lambda msg, **kw: "tratado como staff")

    resposta = pm.processar_mensagem_recebida(_payload_reply_staff(), responder_via_whatsapp=True)

    assert resposta == "tratado como staff"
    assert chamado_fluxo_inquilino == []  # nunca tentou resolver telefone dela como inquilino


def test_sem_context_id_pede_para_usar_responder(monkeypatch, staff_configurada):
    chamadas_texto = []
    monkeypatch.setattr(
        pm.whatsapp_client, "enviar_texto", lambda tel, txt: chamadas_texto.append((tel, txt))
    )

    resposta = pm.processar_mensagem_recebida(
        _payload_reply_staff(wamid_respondido=None), responder_via_whatsapp=True
    )

    assert "Responder" in resposta
    assert chamadas_texto == [("+5581988887777", resposta)]


def test_wamid_sem_escalonamento_correspondente(monkeypatch, staff_configurada):
    monkeypatch.setattr(pm, "identificar_contrato_por_wamid", lambda wamid: None)
    chamadas_texto = []
    monkeypatch.setattr(
        pm.whatsapp_client, "enviar_texto", lambda tel, txt: chamadas_texto.append((tel, txt))
    )

    resposta = pm.processar_mensagem_recebida(_payload_reply_staff(), responder_via_whatsapp=True)

    assert "Não encontrei um caso em aberto" in resposta
    assert chamadas_texto == [("+5581988887777", resposta)]


def test_identificar_contrato_falha_nao_propaga(monkeypatch, staff_configurada):
    def _falha(wamid):
        raise RuntimeError("Supabase fora do ar")

    monkeypatch.setattr(pm, "identificar_contrato_por_wamid", _falha)
    chamadas_texto = []
    monkeypatch.setattr(
        pm.whatsapp_client, "enviar_texto", lambda tel, txt: chamadas_texto.append((tel, txt))
    )

    resposta = pm.processar_mensagem_recebida(_payload_reply_staff(), responder_via_whatsapp=True)

    assert "problema para localizar" in resposta
    assert chamadas_texto == [("+5581988887777", resposta)]


def test_escalonamento_ja_resolvido_nao_reenvia(monkeypatch, staff_configurada):
    monkeypatch.setattr(pm, "identificar_contrato_por_wamid", lambda wamid: "contract-1")
    monkeypatch.setattr(pm, "obter_client_agente", lambda cid: object())
    monkeypatch.setattr(pm, "obter_escalonamento_aberto", lambda client, wamid: None)
    chamadas_texto = []
    monkeypatch.setattr(
        pm.whatsapp_client, "enviar_texto", lambda tel, txt: chamadas_texto.append((tel, txt))
    )

    resposta = pm.processar_mensagem_recebida(_payload_reply_staff(), responder_via_whatsapp=True)

    assert "não está mais em aberto" in resposta
    assert chamadas_texto == [("+5581988887777", resposta)]


_ESCALONAMENTO_ABERTO = {
    "protocolo": "ESC-2026-00001",
    "motivo": "sem_clausula",
    "descricao": "Posso ter cachorro?",
    "telefone_whatsapp": "+5581999998888",
}


def test_fluxo_completo_repassa_resposta_ao_inquilino_e_marca_resolvido(monkeypatch, staff_configurada):
    monkeypatch.setattr(pm, "identificar_contrato_por_wamid", lambda wamid: "contract-1")
    monkeypatch.setattr(pm, "obter_client_agente", lambda cid: object())
    monkeypatch.setattr(
        pm, "obter_escalonamento_aberto", lambda client, wamid: dict(_ESCALONAMENTO_ABERTO)
    )
    monkeypatch.setattr(
        pm,
        "compor_resposta_inquilino",
        lambda pergunta, resposta: "Não, animais de estimação não são permitidos.",
    )
    chamadas_marcar = []
    monkeypatch.setattr(
        pm, "marcar_resolvido", lambda client, protocolo: chamadas_marcar.append(protocolo) or True
    )
    enviados_inquilino = []
    monkeypatch.setattr(
        pm, "enviar_saida", lambda tel, saida: enviados_inquilino.append((tel, saida))
    )
    chamadas_texto_staff = []
    monkeypatch.setattr(
        pm.whatsapp_client, "enviar_texto", lambda tel, txt: chamadas_texto_staff.append((tel, txt))
    )

    resposta = pm.processar_mensagem_recebida(_payload_reply_staff(texto="não"), responder_via_whatsapp=True)

    assert resposta == "Não, animais de estimação não são permitidos."
    assert enviados_inquilino == [
        ("+5581999998888", enviados_inquilino[0][1])
    ]  # foi pro telefone do INQUILINO, não da staff
    assert chamadas_marcar == ["ESC-2026-00001"]
    assert chamadas_texto_staff == [("+5581988887777", "Repassado ao inquilino! (protocolo ESC-2026-00001)")]


def test_falha_ao_enviar_ao_inquilino_nao_marca_resolvido(monkeypatch, staff_configurada):
    monkeypatch.setattr(pm, "identificar_contrato_por_wamid", lambda wamid: "contract-1")
    monkeypatch.setattr(pm, "obter_client_agente", lambda cid: object())
    monkeypatch.setattr(
        pm, "obter_escalonamento_aberto", lambda client, wamid: dict(_ESCALONAMENTO_ABERTO)
    )
    monkeypatch.setattr(pm, "compor_resposta_inquilino", lambda pergunta, resposta: "Não.")

    def _falha_envio(tel, saida):
        raise RuntimeError("falha de transporte simulada")

    monkeypatch.setattr(pm, "enviar_saida", _falha_envio)
    chamadas_marcar = []
    monkeypatch.setattr(pm, "marcar_resolvido", lambda client, protocolo: chamadas_marcar.append(protocolo))
    chamadas_texto_staff = []
    monkeypatch.setattr(
        pm.whatsapp_client, "enviar_texto", lambda tel, txt: chamadas_texto_staff.append((tel, txt))
    )

    resposta = pm.processar_mensagem_recebida(_payload_reply_staff(), responder_via_whatsapp=True)

    assert "Falha ao enviar" in resposta
    assert chamadas_marcar == []  # nunca marca resolvido se a entrega falhou
    assert chamadas_texto_staff == [
        (
            "+5581988887777",
            "Tive um problema para entregar sua resposta ao inquilino — o caso continua "
            "em aberto, pode tentar de novo.",
        )
    ]


def test_composicao_falha_nao_tenta_enviar_ao_inquilino(monkeypatch, staff_configurada):
    monkeypatch.setattr(pm, "identificar_contrato_por_wamid", lambda wamid: "contract-1")
    monkeypatch.setattr(pm, "obter_client_agente", lambda cid: object())
    monkeypatch.setattr(
        pm, "obter_escalonamento_aberto", lambda client, wamid: dict(_ESCALONAMENTO_ABERTO)
    )

    def _falha_composicao(pergunta, resposta):
        raise RuntimeError("Claude fora do ar")

    monkeypatch.setattr(pm, "compor_resposta_inquilino", _falha_composicao)
    enviados_inquilino = []
    monkeypatch.setattr(pm, "enviar_saida", lambda tel, saida: enviados_inquilino.append((tel, saida)))
    chamadas_texto_staff = []
    monkeypatch.setattr(
        pm.whatsapp_client, "enviar_texto", lambda tel, txt: chamadas_texto_staff.append((tel, txt))
    )

    resposta = pm.processar_mensagem_recebida(_payload_reply_staff(), responder_via_whatsapp=True)

    assert "problema para compor a resposta" in resposta
    assert enviados_inquilino == []
    assert chamadas_texto_staff == [("+5581988887777", resposta)]


def test_modo_simulado_nao_dispara_nenhum_envio_real(monkeypatch, staff_configurada):
    """dev_chat (responder_via_whatsapp=False): nem o inquilino nem a staff
    recebem mensagem real — só devolve o que teria sido mandado."""
    monkeypatch.setattr(pm, "identificar_contrato_por_wamid", lambda wamid: "contract-1")
    monkeypatch.setattr(pm, "obter_client_agente", lambda cid: object())
    monkeypatch.setattr(
        pm, "obter_escalonamento_aberto", lambda client, wamid: dict(_ESCALONAMENTO_ABERTO)
    )
    monkeypatch.setattr(pm, "compor_resposta_inquilino", lambda pergunta, resposta: "Não.")
    enviados_inquilino = []
    monkeypatch.setattr(pm, "enviar_saida", lambda tel, saida: enviados_inquilino.append((tel, saida)))
    chamadas_texto_staff = []
    monkeypatch.setattr(
        pm.whatsapp_client, "enviar_texto", lambda tel, txt: chamadas_texto_staff.append((tel, txt))
    )

    resposta = pm.processar_mensagem_recebida(_payload_reply_staff())  # responder_via_whatsapp padrão: False

    assert "[simulado]" in resposta
    assert "Não." in resposta
    assert enviados_inquilino == []
    assert chamadas_texto_staff == []
