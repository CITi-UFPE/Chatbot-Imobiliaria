"""Ponto de entrada do Agente 3 — Manutenção, chamado pelo orquestrador.

A máquina de estados em si (app/agents/a3_manutencao/fluxo.py) é pura: não
conhece Supabase, JWT nem contract_id — recebe um `EstadoAtendimentoManutencao`
e devolve o próximo. Este módulo é a "cola" que falta pra ligar isso no
mundo real, com três responsabilidades que fluxo.py deliberadamente não tem:

1. Persistência de estado entre mensagens — diferente do A1/A5 (que
   processam cada mensagem isolada), o A3 é multi-turno. O estado é
   carregado/salvo a cada chamada via as RPCs genéricas de
   docs/schemas/007_estado_conversa_agente.sql (agent_get/set/clear_
   conversation_state) — quando a etapa chega em 'finalizado', o estado é
   apagado, pra próxima mensagem sobre manutenção começar do zero em vez de
   cair num estado morto.

2. Dados do imóvel (endereço/identificação) pra `iniciar_atendimento` — em
   vez de criar uma RPC nova só pra isso, reaproveita a mesma
   `buscar_dados_inquilino` que o A1 já usa (docs/schemas/006_a1_rpcs.sql),
   pegando só os dois campos que interessam aqui.

3. Escalonamento passando pelo A5 de verdade — a versão original em
   app/tools/supabase_client.py chamava a RPC agent_create_escalation
   direto, sem passar por app.agents.a5_escalonamento.executar_escalonamento
   — o que pulava a notificação da equipe (notificar_staff). Corrigido
   aqui: o `criar_escalonamento_fn` passado pra processar_turno agora monta
   uma AvaliacaoEscalonamento e chama executar_escalonamento, igual o A1 já
   faz no próprio fallback de loop. A abertura de ticket (abrir_ticket_fn)
   continua reaproveitando app.tools.supabase_client.construir_abrir_ticket_fn
   sem mudança — esse caminho nunca teve o problema de notificação.
"""

import logging

from app.agents.a3_manutencao.fluxo import (
    EstadoAtendimentoManutencao,
    iniciar_atendimento,
    processar_turno,
)
from app.agents.a5_escalonamento import AvaliacaoEscalonamento, executar_escalonamento
from app.agents.a5_escalonamento.notificacao import notificar_staff
from app.orchestrator.agent_auth import assinar_token_agente, obter_client_agente
from app.tools.supabase_client import construir_abrir_ticket_fn

logger = logging.getLogger(__name__)

NOME_AGENTE = "A3"


def _buscar_dados_imovel(contract_id: str) -> tuple[str, str]:
    """(imovel_identificacao, imovel_endereco) — reaproveita buscar_dados_inquilino
    (mesma RPC do A1) só pelos dois campos que iniciar_atendimento/processar_turno
    precisam. Sem validação Pydantic completa aqui de propósito: não vale a pena
    validar os outros 20 campos do contrato só pra usar dois."""
    client = obter_client_agente(contract_id)
    resposta = client.rpc("buscar_dados_inquilino", {}).execute()
    dados = resposta.data or {}
    return dados.get("imovel_identificacao", ""), dados.get("imovel_endereco", "")


def _carregar_estado(contract_id: str) -> EstadoAtendimentoManutencao | None:
    client = obter_client_agente(contract_id)
    resposta = client.rpc("agent_get_conversation_state", {"p_agente": NOME_AGENTE}).execute()
    if not resposta.data:
        return None
    return EstadoAtendimentoManutencao.model_validate(resposta.data)


def _salvar_estado(contract_id: str, estado: EstadoAtendimentoManutencao) -> None:
    client = obter_client_agente(contract_id)
    client.rpc(
        "agent_set_conversation_state",
        {"p_agente": NOME_AGENTE, "p_estado": estado.model_dump()},
    ).execute()


def _limpar_estado(contract_id: str) -> None:
    client = obter_client_agente(contract_id)
    client.rpc("agent_clear_conversation_state", {"p_agente": NOME_AGENTE}).execute()


def _criar_escalonamento_fn(contract_id: str):
    """Adapta a assinatura CriarEscalonamentoFn (motivo, descricao) -> None,
    esperada por fluxo.processar_turno, para o caminho real do A5 (que
    grava o protocolo E notifica a staff) — em vez da chamada direta à RPC
    que supabase_client.criar_escalonamento fazia."""

    def _fn(motivo: str, descricao: str) -> None:
        avaliacao = AvaliacaoEscalonamento(
            motivo=motivo,
            descricao=descricao,
            # Não usado neste caminho — fluxo.py já monta a própria mensagem
            # pro inquilino (ResultadoTurno.resposta_inquilino) antes de
            # chamar esta função; resposta_para_inquilino é campo obrigatório
            # de AvaliacaoEscalonamento, mas quem consome é só o log/auditoria.
            resposta_para_inquilino=descricao,
        )
        executar_escalonamento(contract_id, avaliacao)

    return _fn


def responder_manutencao(contract_id: str, mensagem_atual: str, historico_conversa: str = "") -> str:
    """Ponto de entrada do A3, chamado pelo orquestrador depois que o roteador
    já decidiu que esta mensagem é um caso de manutenção.

    historico_conversa não é usado aqui (diferente do A1/A5) — o A3 não
    precisa dele porque já mantém o próprio estado estruturado entre turnos;
    o parâmetro existe só pra manter a mesma assinatura dos outros
    `_rotear_para_*` do orquestrador.
    """
    imovel_identificacao, imovel_endereco = _buscar_dados_imovel(contract_id)

    estado = _carregar_estado(contract_id)
    access_token = assinar_token_agente(contract_id)
    abrir_ticket_fn = construir_abrir_ticket_fn(access_token)
    criar_escalonamento_fn = _criar_escalonamento_fn(contract_id)

    if estado is None:
        resultado = iniciar_atendimento(
            imovel_endereco=imovel_endereco,
            imovel_numero=imovel_identificacao,
        )
    else:
        resultado = processar_turno(
            estado,
            mensagem_atual,
            imovel_endereco=imovel_endereco,
            imovel_numero=imovel_identificacao,
            abrir_ticket_fn=abrir_ticket_fn,
            criar_escalonamento_fn=criar_escalonamento_fn,
        )

    if resultado.estado.etapa == "finalizado":
        _limpar_estado(contract_id)
    else:
        _salvar_estado(contract_id, resultado.estado)

    if resultado.notificacao_gestora:
        notificar_staff(resultado.notificacao_gestora)

    return resultado.resposta_inquilino
