-- ============================================================
-- MIGRATION 022 — Resposta da gestora via reply nativo (A5)
-- ============================================================
-- Depende das Migrations 001, 002 e 004 já terem rodado (tabela
-- escalations, agent_contract_id(), agent_create_escalation).
--
-- Contexto: hoje quando o A5 escala um caso (ex: pergunta sem cláusula
-- correspondente), a Fernanda recebe a notificação mas tem que ir
-- pessoalmente resolver com o inquilino — não existe caminho de volta.
-- Esta migration abre espaço no schema para correlacionar a RESPOSTA dela
-- (reply nativo do WhatsApp, usando o campo `context.id` do payload da
-- Meta) com a escalação certa, mesmo com múltiplos casos abertos ao mesmo
-- tempo — sem isso, uma resposta em texto livre não tem como dizer
-- sozinha "isso é sobre o inquilino X".
--
-- Duas novas funções seguem o MESMO padrão de resolver_contrato_por_telefone
-- (Migration 004/019 — anon, só devolve um identificador mínimo) e das
-- funções agent_* já existentes (escopadas por agent_contract_id(), nunca
-- recebem contract_id como parâmetro):
--   1) resolver_escalonamento_por_wamid — papel anon, usada ANTES de existir
--      um contract_id pra montar o JWT do agente (mesma situação de
--      resolver_contrato_por_telefone). Só devolve o contract_id.
--   2) agent_obter_escalonamento_aberto_por_wamid — já com o token escopado,
--      devolve os dados necessários pra compor a resposta ao inquilino
--      (descrição original, protocolo, telefone).
--
-- Marcar como resolvido é uma operação SEPARADA (agent_marcar_escalonamento_
-- resolvido), chamada só depois que a mensagem de fato foi entregue ao
-- inquilino — se o envio falhar, a escalação continua 'aberto' e a mesma
-- resposta da gestora pode ser reprocessada depois (o wamid da notificação
-- original não muda), sem exigir nenhum controle extra de retry.
-- ============================================================

begin;

alter table public.escalations
  add column if not exists notificacao_wamid text;

-- Único: cada notificação enviada à equipe corresponde a no máximo uma
-- escalação (é o próprio id da mensagem que a Meta atribuiu no envio).
create unique index if not exists escalations_notificacao_wamid_uidx
  on public.escalations (notificacao_wamid)
  where notificacao_wamid is not null;

-- ------------------------------------------------------------
-- 22.1 — Grava o wamid da notificação já enviada à equipe, logo após
-- executar_escalonamento() ter o protocolo em mãos (o wamid só existe
-- DEPOIS do envio — não dá pra gravar tudo numa única chamada a
-- agent_create_escalation).
-- ------------------------------------------------------------
create or replace function public.agent_registrar_wamid_escalonamento(
  p_protocolo text,
  p_wamid text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_atualizou boolean;
begin
  update public.escalations
  set notificacao_wamid = p_wamid
  where protocolo = p_protocolo
    and contract_id = public.agent_contract_id()
    and status = 'aberto'
  returning true into v_atualizou;

  return coalesce(v_atualizou, false);
end;
$$;

revoke all on function public.agent_registrar_wamid_escalonamento(text, text) from public;
grant execute on function public.agent_registrar_wamid_escalonamento(text, text) to agente_ia;

-- ------------------------------------------------------------
-- 22.2 — Resolução de contract_id a partir do wamid respondido, sem
-- service_role (mesmo racional de resolver_contrato_por_telefone).
-- ------------------------------------------------------------
create or replace function public.resolver_escalonamento_por_wamid(p_wamid text)
returns uuid
language sql
security definer
stable
set search_path = ''
as $$
  select contract_id
  from public.escalations
  where notificacao_wamid = p_wamid
    and status = 'aberto'
  limit 1;
$$;

revoke all on function public.resolver_escalonamento_por_wamid(text) from public;
grant execute on function public.resolver_escalonamento_por_wamid(text) to anon;

-- ------------------------------------------------------------
-- 22.3 — Dados da escalação aberta (já com o token escopado por contrato)
-- pra compor a resposta ao inquilino: descrição original (a pergunta),
-- protocolo (pra marcar resolvido depois) e o telefone do inquilino.
-- ------------------------------------------------------------
create or replace function public.agent_obter_escalonamento_aberto_por_wamid(p_wamid text)
returns jsonb
language sql
security definer
stable
set search_path = ''
as $$
  select jsonb_build_object(
    'protocolo', e.protocolo,
    'motivo', e.motivo,
    'descricao', e.descricao,
    'telefone_whatsapp', c.telefone_whatsapp
  )
  from public.escalations e
  join public.contracts c on c.id = e.contract_id
  where e.notificacao_wamid = p_wamid
    and e.status = 'aberto'
    and e.contract_id = public.agent_contract_id()
  limit 1;
$$;

revoke all on function public.agent_obter_escalonamento_aberto_por_wamid(text) from public;
grant execute on function public.agent_obter_escalonamento_aberto_por_wamid(text) to agente_ia;

-- ------------------------------------------------------------
-- 22.4 — Marca resolvido. Guard "where status = 'aberto'" é o próprio
-- controle de idempotência (mesmo padrão de agent_finalizar_contrato,
-- Migration 012): reprocessar a mesma resposta da gestora não tem efeito
-- na segunda vez.
-- ------------------------------------------------------------
create or replace function public.agent_marcar_escalonamento_resolvido(p_protocolo text)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_atualizou boolean;
begin
  update public.escalations
  set status = 'resolvido'
  where protocolo = p_protocolo
    and contract_id = public.agent_contract_id()
    and status = 'aberto'
  returning true into v_atualizou;

  return coalesce(v_atualizou, false);
end;
$$;

revoke all on function public.agent_marcar_escalonamento_resolvido(text) from public;
grant execute on function public.agent_marcar_escalonamento_resolvido(text) to agente_ia;

comment on column public.escalations.notificacao_wamid is
  'Id (wamid) da mensagem de notificação enviada à equipe — usado para correlacionar o reply nativo dela com esta escalação.';
comment on function public.agent_registrar_wamid_escalonamento(text, text) is
  'Grava o wamid da notificação já enviada, para permitir correlacionar a resposta da gestora depois.';
comment on function public.resolver_escalonamento_por_wamid(text) is
  'Retorna o contract_id da escalação aberta correspondente ao wamid respondido, ou null.';
comment on function public.agent_obter_escalonamento_aberto_por_wamid(text) is
  'Retorna protocolo/motivo/descricao/telefone da escalação aberta correspondente ao wamid, já escopada pelo contrato do JWT.';
comment on function public.agent_marcar_escalonamento_resolvido(text) is
  'Marca a escalação como resolvida; idempotente (segunda chamada não encontra linha em aberto).';

commit;

-- ============================================================
-- FIM DA MIGRATION 022
-- ============================================================
