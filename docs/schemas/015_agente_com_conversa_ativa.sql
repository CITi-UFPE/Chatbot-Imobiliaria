-- ============================================================
-- MIGRATION 015 — Agente com conversa ativa (roteamento)
-- ============================================================
-- Depende da Migration 007 (agent_conversation_states).
--
-- Motivação: rotear_mensagem (app/orchestrator/orchestrator.py) reclassificava
-- TODA mensagem via LLM, mesmo quando já existia uma conversa multi-turno em
-- aberto (ex: A3 aguardando confirmação do imóvel) — uma resposta ambígua do
-- inquilino ("hein? que endereço?") podia ser classificada pra outro agente
-- no meio do fluxo, quebrando a máquina de estados do A3 (MAX_TENTATIVAS_
-- IDENTIFICACAO nunca disparava porque a mensagem nem chegava lá, já que o
-- classificador decidia sem saber que a conversa estava em andamento). Esta
-- RPC deixa o orquestrador checar, antes de classificar, se já existe uma
-- conversa em aberto pra este contrato — e se existir, ir direto pro agente
-- dono dela, sem passar pelo classificador.
-- ============================================================

create or replace function agent_get_active_agent()
returns text
language sql
security definer
stable
as $$
  select agente
  from agent_conversation_states
  where contract_id = agent_contract_id()
  limit 1;
$$;

grant execute on function agent_get_active_agent() to agente_ia;

-- ============================================================
-- FIM DA MIGRATION 015
-- ============================================================
