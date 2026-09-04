"""executar_escalonamento (A5) precisa buscar nome/imóvel/telefone do
inquilino e repassar pra notificar_staff_escalonamento — sem isso a equipe
recebe a notificação sem saber quem escreveu (bug relatado, ver
docs/superpowers/plans/2026-09-03-correcoes-fluxo-escalonamento/02-...).
"""

from unittest.mock import MagicMock

from app.agents.a5_escalonamento import escalonamento as esc
from app.agents.a5_escalonamento.escalonamento import AvaliacaoEscalonamento


def _avaliacao() -> AvaliacaoEscalonamento:
    return AvaliacaoEscalonamento(
        motivo="pedido_humano",
        descricao="Inquilino pediu para falar com a equipe.",
        resposta_para_inquilino="Já encaminhei seu caso.",
    )


class _ClientFake:
    def __init__(self, dados_contrato: dict):
        self._dados_contrato = dados_contrato
        self._ultimo_nome = ""

    def rpc(self, nome, params):
        self._ultimo_nome = nome
        return self

    def execute(self):
        if self._ultimo_nome == "agent_create_escalation":
            return MagicMock(data="ESC-2026-00099")
        if self._ultimo_nome == "buscar_dados_cobranca_contrato":
            return MagicMock(data=self._dados_contrato)
        return MagicMock(data=None)


def test_notifica_com_nome_imovel_e_telefone_do_contrato(monkeypatch):
    client = _ClientFake(
        {
            "inquilino_nome": "João Pereira",
            "imovel_identificacao": "Apto 305",
            "telefone_whatsapp": "+5581999998888",
        }
    )
    monkeypatch.setattr(esc, "obter_client_agente", lambda contract_id: client)

    chamadas = []
    monkeypatch.setattr(
        esc,
        "notificar_staff_escalonamento",
        lambda protocolo, motivo, descricao, nome, imovel, telefone: chamadas.append(
            (protocolo, motivo, descricao, nome, imovel, telefone)
        ),
    )

    protocolo = esc.executar_escalonamento("contract-1", _avaliacao())

    assert protocolo == "ESC-2026-00099"
    assert chamadas == [
        (
            "ESC-2026-00099",
            "pedido_humano",
            "Inquilino pediu para falar com a equipe.",
            "João Pereira",
            "Apto 305",
            "+5581999998888",
        )
    ]


def test_falha_ao_buscar_dados_do_contrato_ainda_assim_notifica(monkeypatch, caplog):
    """Regra de resiliência: se buscar_dados_cobranca_contrato falhar (banco
    instável, contrato não encontrado etc.), a escalação já foi gravada — a
    notificação ainda tem que sair, só sem os 3 campos extras."""
    client = _ClientFake({})
    rpc_original = client.rpc

    def _rpc_com_falha(nome, params):
        if nome == "buscar_dados_cobranca_contrato":
            raise RuntimeError("falha simulada de banco")
        return rpc_original(nome, params)

    monkeypatch.setattr(client, "rpc", _rpc_com_falha)
    monkeypatch.setattr(esc, "obter_client_agente", lambda contract_id: client)

    chamadas = []
    monkeypatch.setattr(
        esc,
        "notificar_staff_escalonamento",
        lambda protocolo, motivo, descricao, nome, imovel, telefone: chamadas.append(
            (protocolo, motivo, descricao, nome, imovel, telefone)
        ),
    )

    with caplog.at_level("ERROR"):
        protocolo = esc.executar_escalonamento("contract-1", _avaliacao())

    assert protocolo == "ESC-2026-00099"
    assert chamadas == [("ESC-2026-00099", "pedido_humano", "Inquilino pediu para falar com a equipe.", "", "", "")]
