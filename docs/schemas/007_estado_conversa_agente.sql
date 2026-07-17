-- ============================================================
-- MIGRATION 007 — Persistência de estado de conversa (genérica)
-- ============================================================
-- Depende das Migrations 001 e 002 já terem rodado (agent_contract_id()).
--
-- Motivação: o A3 (Manutenção) é uma máquina de estados multi-turno
-- (app/agents/a3_manutencao/fluxo.py — aguardando_confirmacao_imovel ->
-- aguardando_descricao -> aguardando_esclarecimento -> finalizado), mas até
-- agora não existia nenhum lugar para guardar ESSE estado entre uma
-- mensagem do WhatsApp e a próxima — o orquestrador processa cada mensagem
-- de forma isolada (ver app/orchestrator/processar_mensagem.py).
--
-- Desenho: uma tabela e três RPCs genéricas, não específicas do A3. Motivo:
-- outros agentes com fluxo multi-turno no futuro (ex: uma negociação de
-- cobrança do A2 que precise de mais de uma pergunta) podem reaproveitar a
-- mesma tabela em vez de cada um inventar seu próprio esquema de estado —
-- só muda o valor da coluna `agente` e o formato do jsonb, que cada agente
-- define e interpreta sozinho (aqui não validamos o formato do jsonb: quem
-- valida é o Pydantic do lado Python, EstadoAtendimentoManutencao no caso
-- do A3 — mesma doutrina de DadosInquilino/RegistroHistorico na Migration
-- 006, validar o retorno do banco na camada Python, não dentro do SQL).
--
-- Chave primária composta (contract_id, agente): cada contrato tem no
-- máximo UM estado em aberto por agente ao mesmo tempo — não existe hoje
-- caso de uso de duas conversas de manutenção simultâneas no mesmo
-- contrato, e se surgir, é uma decisão de produto pra revisitar este
-- desenho, não um acidente de schema.
-- ============================================================

create table if not exists agent_conversation_states (
  contract_id   uuid not null references contracts(id) on delete cascade,
  agente        text not null check (agente in ('A1', 'A2', 'A3', 'A4', 'A5')),
  estado        jsonb not null,
  updated_at    timestamptz not null default now(),
  primary key (contract_id, agente)
);

create index if not exists agent_conversation_states_contract_id_idx
  on agent_conversation_states (contract_id);

-- Fail-closed, sem policies — mesmo padrão de protocolo_counters (Migration
-- 005): só acessada de dentro das funções security definer abaixo.
alter table agent_conversation_states enable row level security;

-- ------------------------------------------------------------
-- agent_get_conversation_state — devolve o estado salvo (ou null, se esta
-- for a primeira mensagem do fluxo) para o agente da CHAMADA ATUAL — nunca
-- recebe contract_id como parâmetro, resolve via agent_contract_id() como
-- todas as outras RPCs do agente.
-- ------------------------------------------------------------
create or replace function agent_get_conversation_state(p_agente text)
returns jsonb
language sql
security definer
stable
as $$
  select estado
  from agent_conversation_states
  where contract_id = agent_contract_id()
    and agente = p_agente;
$$;

grant execute on function agent_get_conversation_state(text) to agente_ia;

-- ------------------------------------------------------------
-- agent_set_conversation_state — grava/atualiza o estado (upsert). Chamada
-- a cada turno do fluxo, com o jsonb já serializado do lado Python
-- (EstadoAtendimentoManutencao.model_dump(), no caso do A3).
-- ------------------------------------------------------------
create or replace function agent_set_conversation_state(p_agente text, p_estado jsonb)
returns void
language plpgsql
security definer
as $$
begin
  insert into agent_conversation_states (contract_id, agente, estado, updated_at)
  values (agent_contract_id(), p_agente, p_estado, now())
  on conflict (contract_id, agente)
  do update set estado = excluded.estado, updated_at = now();
end;
$$;

grant execute on function agent_set_conversation_state(text, jsonb) to agente_ia;

-- ------------------------------------------------------------
-- agent_clear_conversation_state — apaga o estado quando o fluxo termina
-- (etapa = 'finalizado'), pra próxima mensagem do inquilino nesse assunto
-- começar do zero em vez de cair num estado "finalizado" morto.
-- ------------------------------------------------------------
create or replace function agent_clear_conversation_state(p_agente text)
returns void
language plpgsql
security definer
as $$
begin
  delete from agent_conversation_states
  where contract_id = agent_contract_id()
    and agente = p_agente;
end;
$$;

grant execute on function agent_clear_conversation_state(text) to agente_ia;

-- ============================================================
-- FIM DA MIGRATION 007
-- ============================================================
