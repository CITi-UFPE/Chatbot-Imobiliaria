-- ============================================================
-- MIGRATION 004 — Protocolo de escalonamento + resolução de contrato
-- por telefone (Projeto Domingos)
-- ============================================================
-- Depende das Migrations 001, 002 e 003 já terem rodado.
--
-- Duas mudanças, ambas necessárias para o backend (JWT do agente, webhook
-- do WhatsApp e A5 — Escalonamento):
--
-- 1) agent_create_escalation (Migration 002) nunca preenchia a coluna
--    `protocolo` — ficava sempre NULL. Precisamos de um número sequencial
--    legível (ex: "ESC-2026-00042") para devolver ao inquilino/gestora
--    quando o A5 escala um caso. Isso não pode ser calculado em Python pelo
--    client do agente: o token agente_ia só enxerga, via RLS, os registros
--    do PRÓPRIO contrato — não daria para contar quantas escalações existem
--    no total. A função já é SECURITY DEFINER, então é o lugar certo para
--    essa lógica (roda com privilégio, independente da RLS do chamador).
--
-- 2) Nova função resolver_contrato_por_telefone: antes de saber o
--    contract_id de uma conversa recém-chegada do WhatsApp, o backend não
--    tem como montar o JWT escopado do agente (contract_id é exatamente o
--    dado que falta). Em vez de usar a service_role key nesse primeiro
--    passo — o que fugiria do padrão "toda leitura/escrita do agente passa
--    por função dedicada" estabelecido na Migration 002 — criamos uma
--    função SECURITY DEFINER liberada para o papel "anon". Ela só devolve
--    um UUID de contrato dado um telefone; nada mais sensível do que isso
--    fica exposto.
-- ============================================================

-- ------------------------------------------------------------
-- 4.1 — Protocolo sequencial em agent_create_escalation
--
-- Precisa dropar antes de recriar porque o tipo de retorno muda
-- (uuid -> text): create or replace function não permite mudar o tipo de
-- retorno de uma função existente.
-- ------------------------------------------------------------
drop function if exists agent_create_escalation(text, text);

create sequence if not exists escalation_protocolo_seq;

create function agent_create_escalation(
  p_motivo text,
  p_descricao text
)
returns text -- devolve o protocolo diretamente: é o que o A5 precisa para responder o inquilino
language plpgsql
security definer
as $$
declare
  v_protocolo text;
begin
  v_protocolo := 'ESC-' || to_char(now(), 'YYYY') || '-'
    || lpad(nextval('escalation_protocolo_seq')::text, 5, '0');

  insert into escalations (contract_id, motivo, descricao, protocolo)
  values (agent_contract_id(), p_motivo, p_descricao, v_protocolo);

  return v_protocolo;
end;
$$;

-- Recriar a função (drop + create) apaga os GRANTs anteriores — repetir aqui.
grant execute on function agent_create_escalation(text, text) to agente_ia;
grant usage, select on sequence escalation_protocolo_seq to agente_ia;

-- ------------------------------------------------------------
-- 4.2 — Resolução de contract_id por telefone, sem service_role
-- ------------------------------------------------------------
create or replace function resolver_contrato_por_telefone(p_telefone text)
returns uuid
language sql
security definer
stable
as $$
  select id from contracts
  where telefone_whatsapp = p_telefone and status = 'ativo'
  limit 1;
$$;

grant execute on function resolver_contrato_por_telefone(text) to anon;

-- ============================================================
-- FIM DA MIGRATION 004
-- ============================================================
