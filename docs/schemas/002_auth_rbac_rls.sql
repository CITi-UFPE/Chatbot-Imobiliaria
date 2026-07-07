-- ============================================================
-- MIGRATION 002 — Auth, RBAC e políticas de RLS (Projeto Domingos)
-- ============================================================
-- Depende da Migration 001 já ter rodado.
--
-- Responde as três perguntas do briefing:
--  1) Quem entra                -> seções 2.1 e 2.2
--  2) O que cada um pode fazer  -> seções 2.3 em diante (policies)
--                                  + seção 2.9 (funções RPC do agente)
--  3) Isolamento por contrato   -> agent_contract_id() + toda policy
--                                  "agent_*" abaixo, e Storage (2.11)
-- ============================================================

-- ------------------------------------------------------------
-- 2.1 — STAFF_USERS: liga um login humano (Supabase Auth) a um papel.
-- Fernanda, Domingos e qualquer outro humano que precise entrar no
-- Lovable ganham uma linha aqui. auth.users já existe nativamente.
-- ------------------------------------------------------------
create table staff_users (
  user_id     uuid primary key references auth.users(id) on delete cascade,
  nome        text not null,
  role        text not null check (role in ('gestora', 'owner', 'customer_success')),
  created_at  timestamptz not null default now()
);

-- Mesma lógica fail-closed da Migration 001: liga RLS e não abre
-- nenhuma policy de select/insert/update pro authenticated aqui.
-- Só service_role (dashboard/admin) enxerga essa tabela diretamente;
-- is_staff() abaixo é security definer, então continua funcionando
-- normalmente pra qualquer política que dependa dela.
alter table staff_users enable row level security;

create or replace function is_staff()
returns boolean
language sql
security definer
stable
as $$
  select exists (select 1 from staff_users where user_id = auth.uid());
$$;

-- ------------------------------------------------------------
-- 2.2 — IDENTIDADE DO AGENTE: token escopado por contrato, NÃO a
-- chave mestra (service_role).
--
-- O backend dos agentes autentica com um papel dedicado do Postgres
-- ("agente_ia", criado na seção 2.10) e, a cada mensagem recebida no
-- WhatsApp, o próprio backend resolve de qual contract_id é aquele
-- número de telefone e assina um JWT contendo essa claim. É esse
-- token — nunca a service_role key — que consulta o banco para
-- aquela conversa específica.
--
-- Resultado prático: mesmo que o código do agente tenha um bug e
-- busque/misture o contrato errado, o token daquela conversa
-- fisicamente não tem permissão de enxergar outro contract_id.
-- A trava está no banco, não no código da aplicação.
-- ------------------------------------------------------------
create or replace function agent_contract_id()
returns uuid
language sql
stable
as $$
  select nullif(current_setting('request.jwt.claims', true)::json->>'contract_id', '')::uuid;
$$;

-- ------------------------------------------------------------
-- 2.3 — POLICIES: contracts
-- ------------------------------------------------------------
create policy staff_full_access on contracts
  for all using (is_staff()) with check (is_staff());

create policy agent_read_own_contract on contracts
  for select using (id = agent_contract_id());

-- ------------------------------------------------------------
-- 2.4 — POLICIES: contract_clauses
-- ------------------------------------------------------------
create policy staff_full_access on contract_clauses
  for all using (is_staff()) with check (is_staff());

create policy agent_read_own_clauses on contract_clauses
  for select using (contract_id = agent_contract_id());

-- ------------------------------------------------------------
-- 2.5 — POLICIES: charges
-- ------------------------------------------------------------
create policy staff_full_access on charges
  for all using (is_staff()) with check (is_staff());

create policy agent_read_own_charges on charges
  for select using (contract_id = agent_contract_id());
-- Não existe policy de insert/update para o agente aqui de propósito:
-- toda escrita do agente em charges passa pela função
-- agent_update_charge_status (seção 2.9), nunca por UPDATE direto.

-- ------------------------------------------------------------
-- 2.6 — POLICIES: charge_negotiations (decisão é só humana)
-- ------------------------------------------------------------
create policy staff_full_access on charge_negotiations
  for all using (is_staff()) with check (is_staff());

-- O agente só lê, para saber se uma cobrança já foi negociada.
-- Nunca decide nem grava perdão de multa sozinho.
create policy agent_read_negotiations on charge_negotiations
  for select using (
    exists (
      select 1 from charges
      where charges.id = charge_negotiations.charge_id
      and charges.contract_id = agent_contract_id()
    )
  );

-- ------------------------------------------------------------
-- 2.7 — POLICIES: maintenance_tickets, escalations, contract_alerts,
-- conversation_logs — mesmo padrão: staff vê tudo, agente só o
-- próprio contrato, e a escrita do agente é via RPC (seção 2.9).
-- ------------------------------------------------------------
create policy staff_full_access on maintenance_tickets
  for all using (is_staff()) with check (is_staff());
create policy agent_read_own_tickets on maintenance_tickets
  for select using (contract_id = agent_contract_id());

create policy staff_full_access on escalations
  for all using (is_staff()) with check (is_staff());
create policy agent_read_own_escalations on escalations
  for select using (contract_id = agent_contract_id());

create policy staff_full_access on contract_alerts
  for all using (is_staff()) with check (is_staff());
create policy agent_read_own_alerts on contract_alerts
  for select using (contract_id = agent_contract_id());

create policy staff_full_access on conversation_logs
  for all using (is_staff()) with check (is_staff());
create policy agent_read_own_logs on conversation_logs
  for select using (contract_id = agent_contract_id());

-- ------------------------------------------------------------
-- 2.8 — Nenhuma policy "for delete" foi criada para o agente em
-- lugar nenhum acima. Reforço explícito: revoga DELETE também no
-- nível de GRANT para o papel authenticated (usado pelo staff via
-- Supabase Auth). Apagar de verdade só acontece via service_role,
-- manualmente, num fluxo formal de exclusão de dados (LGPD) — nunca
-- num clique do dia a dia, nem do staff nem do agente.
-- ------------------------------------------------------------
revoke delete on
  contracts, contract_clauses, charges, charge_negotiations,
  maintenance_tickets, escalations, contract_alerts, conversation_logs
from authenticated;

-- ------------------------------------------------------------
-- 2.9 — FUNÇÕES DE ESCRITA DO AGENTE (RPC, SECURITY DEFINER)
--
-- O agente nunca recebe INSERT/UPDATE direto nas tabelas. Cada
-- "skill" do agente (registrar pagamento, abrir chamado, escalar,
-- logar mensagem) vira uma função que já embute a regra de negócio:
-- que coluna pode mudar, em qual contrato, e nada além disso.
--
-- Por quê não usar GRANT de coluna direto nas tabelas? Porque no
-- Supabase, staff e agente autenticam como papéis diferentes só se
-- configurarmos isso explicitamente (seção 2.10) — sem essa
-- separação, um GRANT de coluna valeria pros dois ao mesmo tempo.
-- Empacotar a escrita numa função resolve isso de forma limpa e
-- também deixa auditável: cada ação do agente é uma chamada nomeada,
-- não um UPDATE genérico solto no meio do código do backend.
-- ------------------------------------------------------------

create or replace function agent_update_charge_status(
  p_charge_id uuid,
  p_status text,
  p_valor_identificado numeric default null,
  p_data_pagamento date default null
)
returns void
language plpgsql
security definer
as $$
begin
  update charges
  set status = p_status,
      valor_identificado = coalesce(p_valor_identificado, valor_identificado),
      data_pagamento = coalesce(p_data_pagamento, data_pagamento),
      updated_at = now()
  where id = p_charge_id
    and contract_id = agent_contract_id(); -- trava de isolamento dentro da própria função
end;
$$;

create or replace function agent_open_maintenance_ticket(
  p_categoria text,
  p_urgencia text,
  p_descricao text
)
returns uuid
language plpgsql
security definer
as $$
declare
  v_id uuid;
begin
  insert into maintenance_tickets (contract_id, categoria, urgencia, descricao)
  values (agent_contract_id(), p_categoria, p_urgencia, p_descricao)
  returning id into v_id;
  return v_id;
end;
$$;

create or replace function agent_create_escalation(
  p_motivo text,
  p_descricao text
)
returns uuid
language plpgsql
security definer
as $$
declare
  v_id uuid;
begin
  insert into escalations (contract_id, motivo, descricao)
  values (agent_contract_id(), p_motivo, p_descricao)
  returning id into v_id;
  return v_id;
end;
$$;

create or replace function agent_log_message(
  p_remetente text,
  p_agente_responsavel text,
  p_mensagem text
)
returns void
language plpgsql
security definer
as $$
begin
  insert into conversation_logs (contract_id, remetente, agente_responsavel, mensagem)
  values (agent_contract_id(), p_remetente, p_agente_responsavel, p_mensagem);
end;
$$;

-- ------------------------------------------------------------
-- 2.10 — PAPEL DEDICADO DO AGENTE ("agente_ia")
--
-- Cria um papel do Postgres separado do "authenticated" padrão do
-- Supabase, só para o backend dos agentes. Ele recebe apenas:
--   - SELECT nas tabelas que precisa consultar (via policies acima)
--   - EXECUTE nas funções RPC da seção 2.9
-- Nunca GRANT direto de INSERT/UPDATE/DELETE nas tabelas.
--
-- ATENÇÃO — passo manual fora deste arquivo: para o Supabase de
-- fato emitir um JWT com "role": "agente_ia" para o backend, isso
-- precisa ser configurado no projeto (Custom Access Token Hook, ou
-- o mecanismo equivalente disponível na versão de vocês do Supabase
-- Auth). Não escrevi isso aqui porque depende de decisões que só
-- dá pra confirmar olhando o projeto Supabase real de vocês — mas é
-- o próximo passo depois de rodar esta migration, e sem ele o
-- backend continua sem conseguir autenticar como agente_ia.
-- ------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'agente_ia') then
    create role agente_ia nologin;
  end if;
end
$$;

grant agente_ia to authenticator; -- necessário para o PostgREST poder assumir esse papel

grant usage on schema public to agente_ia;
grant select on contracts, contract_clauses, charges, charge_negotiations,
  maintenance_tickets, escalations, contract_alerts, conversation_logs
  to agente_ia;

grant execute on function agent_update_charge_status(uuid, text, numeric, date) to agente_ia;
grant execute on function agent_open_maintenance_ticket(text, text, text) to agente_ia;
grant execute on function agent_create_escalation(text, text) to agente_ia;
grant execute on function agent_log_message(text, text, text) to agente_ia;
grant execute on function agent_contract_id() to agente_ia;

-- Ainda que o agente já não tenha GRANT de insert/update/delete nas
-- tabelas, deixamos explícito para não depender de "ausência" —
-- segurança por omissão é frágil, segurança por revogação explícita
-- é auditável.
revoke insert, update, delete on
  contracts, contract_clauses, charges, charge_negotiations,
  maintenance_tickets, escalations, contract_alerts, conversation_logs
from agente_ia;

-- ------------------------------------------------------------
-- 2.11 — STORAGE: bucket privado dos contratos em PDF
--
-- Implementa o "Upload Blindado e Storage Privado (RLS)" que está
-- na proposta assinada com o Domingos — hoje só existia no papel.
-- ------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('contracts', 'contracts', false)
on conflict (id) do nothing;

-- Staff autenticado lê/escreve qualquer arquivo do bucket (upload
-- feito pela gestora no Lovable).
create policy staff_storage_access on storage.objects
  for all
  using (bucket_id = 'contracts' and is_staff())
  with check (bucket_id = 'contracts' and is_staff());

-- O agente só lê o PDF dentro da pasta do PRÓPRIO contrato.
-- Convenção de caminho obrigatória: contracts/{contract_id}/original.pdf
create policy agent_storage_read_own on storage.objects
  for select
  using (
    bucket_id = 'contracts'
    and (storage.foldername(name))[1] = agent_contract_id()::text
  );

