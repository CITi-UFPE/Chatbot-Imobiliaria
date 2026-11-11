-- ============================================================
-- MIGRATION 026 — conversation_logs.canal
-- ============================================================
-- Depende das Migrations 001 e 002.
--
-- conversation_logs só gravava a conversa com o inquilino. Passa a gravar
-- também o que o sistema manda à administradora (comprovantes, escalonamentos,
-- alertas) e o que ela responde (cliques de botão, reply a escalonamento).
-- Sem distinguir com quem era a conversa, uma mensagem do bot à administradora
-- ficaria idêntica a uma ao inquilino (remetente 'agente' nas duas).
--
-- `canal` = com quem é a conversa do contrato:
--   'inquilino'       — comportamento até aqui (default, linhas antigas)
--   'administradora'  — conversa interna com a gestão/staff, sobre o contrato
--
-- A mensagem da administradora fica no contrato a que se refere
-- (contract_id continua not null). Mensagem sem contrato identificado
-- (ex.: comprovante sem correspondência) NÃO é gravada aqui.
--
-- agent_get_last_tenant_message_at (Migration 020) filtra
-- remetente = 'inquilino' e não é afetada: a administradora grava com
-- remetente 'gestora' (entrada) ou 'agente' (saída).
--
-- Aplicar ANTES de subir o código que envia p_canal. O código só manda p_canal
-- nas mensagens da administradora; as do inquilino seguem funcionando com ou
-- sem esta migration.
-- ============================================================

begin;

alter table conversation_logs
  add column if not exists canal text not null default 'inquilino'
  check (canal in ('inquilino', 'administradora'));

-- Assinatura nova com p_canal (default 'inquilino'). A antiga de 3 argumentos
-- sai: manter as duas deixaria a chamada com 3 parâmetros ambígua
-- ("function is not unique").
drop function if exists agent_log_message(text, text, text);

create or replace function agent_log_message(
  p_remetente text,
  p_agente_responsavel text,
  p_mensagem text,
  p_canal text default 'inquilino'
)
returns void
language plpgsql
security definer
as $$
begin
  insert into conversation_logs (contract_id, remetente, agente_responsavel, mensagem, canal)
  values (agent_contract_id(), p_remetente, p_agente_responsavel, p_mensagem, p_canal);
end;
$$;

grant execute on function agent_log_message(text, text, text, text) to agente_ia;

create index if not exists conversation_logs_contract_id_canal_idx
  on conversation_logs (contract_id, canal, "timestamp");

commit;

-- ============================================================
-- FIM DA MIGRATION 026
-- ============================================================
