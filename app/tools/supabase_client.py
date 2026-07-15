import os
from typing import Callable

from supabase import Client, create_client

from app.models.maintenance import ClassificacaoManutencao, TicketManutencao


def _client_autenticado(access_token: str) -> Client:
    """Client Supabase autenticado com um JWT já assinado para a conversa (role
    agente_ia, escopado por contract_id via agent_contract_id() — ver
    docs/setup-supabase.md seção 5). A assinatura desse token é responsabilidade
    de feat/jwt-webhook-a5, fora do escopo deste módulo — aqui só injetamos o
    token já pronto nas chamadas RPC."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_ANON_KEY"]
    client = create_client(url, key)
    client.postgrest.auth(access_token)
    return client


def abrir_ticket_manutencao(
    access_token: str,
    classificacao: ClassificacaoManutencao,
    descricao_inquilino: str,
    classificacao_incerta: bool,
) -> TicketManutencao:
    client = _client_autenticado(access_token)
    resultado = client.rpc(
        "agent_open_maintenance_ticket",
        {
            "p_categoria": classificacao.categoria,
            "p_urgencia": classificacao.urgencia,
            "p_descricao": descricao_inquilino,
            "p_sinais_risco": list(classificacao.sinais_risco),
            "p_classificacao_incerta": classificacao_incerta,
        },
    ).execute()

    if not resultado.data:
        raise RuntimeError("agent_open_maintenance_ticket não retornou nenhuma linha")

    linha = resultado.data[0]
    return TicketManutencao(
        id=linha["id"],
        protocolo=linha["protocolo"],
        categoria=classificacao.categoria,
        urgencia=classificacao.urgencia,
        descricao=descricao_inquilino,
        sinais_risco=classificacao.sinais_risco,
        classificacao_incerta=classificacao_incerta,
    )


def criar_escalonamento(access_token: str, motivo: str, descricao: str) -> None:
    client = _client_autenticado(access_token)
    client.rpc("agent_create_escalation", {"p_motivo": motivo, "p_descricao": descricao}).execute()


def registrar_mensagem(access_token: str, remetente: str, mensagem: str) -> None:
    client = _client_autenticado(access_token)
    client.rpc(
        "agent_log_message",
        {"p_remetente": remetente, "p_agente_responsavel": "A3", "p_mensagem": mensagem},
    ).execute()


def construir_abrir_ticket_fn(
    access_token: str,
) -> Callable[[ClassificacaoManutencao, str, bool], TicketManutencao]:
    """Fecha access_token no formato AbrirTicketFn esperado por
    app.agents.a3_manutencao.fluxo.processar_turno (que não conhece o token)."""

    def _abrir_ticket(
        classificacao: ClassificacaoManutencao, descricao_inquilino: str, classificacao_incerta: bool
    ) -> TicketManutencao:
        return abrir_ticket_manutencao(access_token, classificacao, descricao_inquilino, classificacao_incerta)

    return _abrir_ticket


def construir_criar_escalonamento_fn(access_token: str) -> Callable[[str, str], None]:
    """Fecha access_token no formato CriarEscalonamentoFn esperado por
    app.agents.a3_manutencao.fluxo.processar_turno (que não conhece o token)."""

    def _criar_escalonamento(motivo: str, descricao: str) -> None:
        criar_escalonamento(access_token, motivo, descricao)

    return _criar_escalonamento
