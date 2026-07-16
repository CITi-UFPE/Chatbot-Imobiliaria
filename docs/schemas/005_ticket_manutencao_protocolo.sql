-- ============================================================
-- MIGRATION 005 — Protocolo e sinais de classificação do A3 (Manutenção)
-- ============================================================
-- Depende das Migrations 001, 002 e 003 já terem rodado.
--
-- Numerada 005, não 004: a branch feat/jwt-webhook-a5 já tem uma migration
-- 004 própria (004_protocolo_e_resolucao_contrato.sql), que também altera
-- agent_create_escalation (passa a devolver o protocolo em texto). Esta
-- migration aqui não toca em agent_create_escalation nem em escalations —
-- só em maintenance_tickets — mas o número foi reservado por aquela branch
-- primeiro. Se o merge de feat/jwt-webhook-a5 mudar esse número, ajustar aqui.
--
-- Origem: spec do agente de manutenção (docs/specs/agente-manutencao.md)
-- referencia um {protocolo} legível nas mensagens ao inquilino/gestora
-- (ex: "chamado MNT-2026-0042"), mas maintenance_tickets só tinha o
-- id (uuid) interno — não dá pra citar um uuid inteiro numa conversa
-- de WhatsApp. A spec também propõe guardar os sinais de risco
-- extraídos pelo LLM (ex: "vazamento grande") e uma marcação de
-- classificação incerta, para a gestora revisar com mais atenção.
-- ============================================================

-- ------------------------------------------------------------
-- 4.1 — Contador de protocolo por ano
--
-- Formato MNT-{ano}-{sequencial com 4 dígitos}, reiniciado a cada
-- ano. Tabela auxiliar (em vez de uma sequence nativa do Postgres)
-- porque sequences não resetam sozinhas por ano — o padrão
-- "insert ... on conflict do update ... returning" abaixo é atômico
-- mesmo com chamadas concorrentes (duas aberturas de ticket ao
-- mesmo tempo nunca recebem o mesmo número).
-- ------------------------------------------------------------
create table if not exists protocolo_counters (
  ano           integer primary key,
  ultimo_numero integer not null default 0
);

alter table protocolo_counters enable row level security;
-- Fail-closed, sem policies: só acessada de dentro da função
-- security definer abaixo (mesmo padrão de 001/002 — o owner da
-- função, não o papel agente_ia, é quem efetivamente grava aqui).

create or replace function gerar_protocolo_manutencao(p_ano integer)
returns text
language plpgsql
security definer
as $$
declare
  v_numero integer;
begin
  insert into protocolo_counters (ano, ultimo_numero)
  values (p_ano, 1)
  on conflict (ano) do update set ultimo_numero = protocolo_counters.ultimo_numero + 1
  returning ultimo_numero into v_numero;

  return 'MNT-' || p_ano || '-' || lpad(v_numero::text, 4, '0');
end;
$$;

-- ------------------------------------------------------------
-- 4.2 — Novas colunas em maintenance_tickets
--
-- protocolo fica nullable no banco (não NOT NULL): é sempre
-- preenchido pela RPC agent_open_maintenance_ticket abaixo, mas
-- deixar como constraint rígida no banco arriscaria quebrar uma
-- inserção manual futura (ex: staff abrindo ticket direto pelo
-- Table Editor) sem necessidade — o índice único abaixo já garante
-- que, quando preenchido, nunca se repete.
-- ------------------------------------------------------------
alter table maintenance_tickets
  add column if not exists protocolo            text,
  add column if not exists sinais_risco         text[] not null default '{}',
  add column if not exists classificacao_incerta boolean not null default false;

create unique index if not exists maintenance_tickets_protocolo_uidx
  on maintenance_tickets (protocolo)
  where protocolo is not null;

-- ------------------------------------------------------------
-- 4.3 — RPC agent_open_maintenance_ticket: assinatura estendida
--
-- A versão original (001/002) tinha 3 parâmetros e devolvia só o
-- uuid. Como a lista de parâmetros muda (novos argumentos, não só
-- um "or replace" compatível), o Postgres trataria isso como um
-- overload novo em vez de substituir a função antiga — por isso o
-- drop explícito abaixo, para não deixar duas versões divergentes
-- coexistindo (a antiga nunca geraria protocolo).
-- ------------------------------------------------------------
drop function if exists agent_open_maintenance_ticket(text, text, text);

create function agent_open_maintenance_ticket(
  p_categoria             text,
  p_urgencia              text,
  p_descricao             text,
  p_sinais_risco          text[] default '{}',
  p_classificacao_incerta boolean default false
)
returns table (id uuid, protocolo text)
language plpgsql
security definer
as $$
declare
  v_id        uuid;
  v_protocolo text;
begin
  v_protocolo := gerar_protocolo_manutencao(extract(year from now())::integer);

  insert into maintenance_tickets (
    contract_id, categoria, urgencia, descricao,
    sinais_risco, classificacao_incerta, protocolo
  )
  values (
    agent_contract_id(), p_categoria, p_urgencia, p_descricao,
    p_sinais_risco, p_classificacao_incerta, v_protocolo
  )
  returning maintenance_tickets.id into v_id;

  return query select v_id, v_protocolo;
end;
$$;

-- gerar_protocolo_manutencao NÃO recebe grant para agente_ia: só é chamada de
-- dentro de agent_open_maintenance_ticket (security definer), que já executa
-- com o privilégio do owner — não precisa do grant do caller na função aninhada.
-- Conceder aqui exporia POST /rpc/gerar_protocolo_manutencao via PostgREST,
-- permitindo avançar o contador do ano sem nunca abrir um ticket.
grant execute on function agent_open_maintenance_ticket(text, text, text, text[], boolean) to agente_ia;

-- ============================================================
-- FIM DA MIGRATION 005
-- ============================================================
