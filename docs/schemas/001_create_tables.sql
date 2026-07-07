-- ============================================================
-- MIGRATION 001 — Estrutura das tabelas (Projeto Domingos)
-- ============================================================
-- Escopo desta entrega: tabelas, tipos, relacionamentos, índices,
-- triggers e integridade referencial/constraints.
--
-- RLS é HABILITADA no fim deste arquivo (fail-closed), mas SEM
-- nenhuma política ainda. Isso é proposital: até a Migration 002
-- rodar, ninguém além do service_role consegue ler ou escrever
-- nessas tabelas. É mais seguro nascer travado e abrir depois do
-- que nascer aberto e travar depois.
-- ============================================================

create extension if not exists pgcrypto;

-- Função reutilizável: mantém updated_at sempre correto.
-- Sem isso, esse campo fica congelado na data de criação para
-- sempre — o Postgres não atualiza timestamps sozinho.
create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ============================================================
-- CONTRACTS
-- ============================================================
create table contracts (
  id                          uuid primary key default gen_random_uuid(),
  imovel_identificacao        text not null,        -- ex: "Apto 2702, Golden Beach"
  imovel_endereco             text not null,
  tipo_locatario              text not null check (tipo_locatario in ('pf', 'pj')),
  inquilino_nome              text not null,        -- ou razão social se pj
  inquilino_cpf_cnpj          text not null,
  responsavel_contato_nome    text,                 -- obrigatório na prática se pj (ex: Frederico Watanabe)
  telefone_whatsapp           text not null,        -- formato +55DDD9XXXXXXXX
  fiador_nome                 text,
  fiador_cpf                  text,
  garantia_tipo               text not null check (garantia_tipo in ('fiador', 'caucao')),
  garantia_valor              numeric,              -- obrigatório só se caucao
  valor_aluguel               numeric not null check (valor_aluguel > 0),
  dia_vencimento              integer not null check (dia_vencimento between 1 and 31),
  vencimento_mes_referencia   text not null default 'atual'
                              check (vencimento_mes_referencia in ('atual', 'anterior')), -- caso Lara/1706
  data_inicio                 date not null,
  data_termino                date not null check (data_termino > data_inicio),
  indice_reajuste             text check (indice_reajuste in ('igpm', 'livre_negociacao')),
  data_aniversario_reajuste   date,                 -- NULL para ARCO (reajuste sem dia fixo)
  multa_infracao_tipo         text not null check (multa_infracao_tipo in ('meses_aluguel', 'percentual_valor_anual')),
  multa_infracao_valor        numeric not null check (multa_infracao_valor > 0), -- 3, 1, ou 10 (%)
  multa_moratoria_percentual  numeric,              -- NULL para ARCO (isento de multa, só juros)
  juros_moratorio_mensal      numeric not null default 0.01,
  aviso_previo_dias           integer not null,
  aviso_previo_a_partir_mes   integer not null,
  banco_agencia               text,
  banco_conta                 text,
  pix_chave                   text,
  status                      text not null default 'pendente_confirmacao'
                              check (status in ('ativo', 'inativo', 'pendente_confirmacao')),
  observacoes                 text,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now(),

  -- Trava de integridade: impede um registro "fiador" sem nome/CPF
  -- de fiador, ou um "caução" sem valor definido. É mais barato
  -- pegar esse erro aqui do que em produção.
  constraint garantia_coerente check (
    (garantia_tipo = 'fiador' and fiador_nome is not null and fiador_cpf is not null)
    or
    (garantia_tipo = 'caucao' and garantia_valor is not null)
  )
);

-- Um número de WhatsApp só pode estar vinculado a UM contrato ATIVO
-- por vez. Sem isso, um erro de cadastro com dois contratos ativos
-- no mesmo número faria o agente responder o inquilino errado com
-- o contrato de outra pessoa — isso É uma falha de isolamento, não
-- só um bug de UX.
create unique index contracts_telefone_ativo_uidx
  on contracts (telefone_whatsapp)
  where status = 'ativo';

create index contracts_status_idx on contracts (status);

create trigger contracts_set_updated_at
  before update on contracts
  for each row execute function set_updated_at();

-- ============================================================
-- CONTRACT_CLAUSES
-- ============================================================
create table contract_clauses (
  id                uuid primary key default gen_random_uuid(),
  contract_id       uuid not null references contracts(id) on delete cascade,
  numero_clausula   text not null,   -- extraído por título/conteúdo, não índice fixo (numeração varia por contrato)
  titulo_clausula   text not null,
  texto_clausula    text not null,
  categoria         text not null check (categoria in (
                      'financeiro', 'benfeitorias', 'sublocacao', 'vistoria',
                      'conservacao', 'agua_energia', 'fiador', 'rescisao', 'multa'
                    )),
  created_at        timestamptz not null default now()
);

create index contract_clauses_contract_id_idx on contract_clauses (contract_id);
create index contract_clauses_categoria_idx on contract_clauses (categoria);

-- ============================================================
-- CHARGES (cobranças — aluguel e água como itens distintos)
-- ============================================================
create table charges (
  id                  uuid primary key default gen_random_uuid(),
  contract_id         uuid not null references contracts(id) on delete cascade,
  tipo                text not null check (tipo in ('aluguel', 'agua')),
  mes_referencia      date not null,
  valor_esperado      numeric not null check (valor_esperado > 0),
  valor_identificado  numeric,          -- extraído do comprovante
  consumo_m3          numeric,          -- só tipo=agua
  data_vencimento     date not null,
  data_pagamento      date,
  dias_atraso         integer not null default 0,
  status              text not null default 'pendente'
                      check (status in (
                        'pendente', 'aguardando_confirmacao', 'confirmado',
                        'divergente', 'atrasado', 'em_negociacao', 'quitado'
                      )),
  comprovante_url     text,
  mensagem_estagio    text check (mensagem_estagio in ('d-5', 'd0', 'd+5', 'd+10', 'd+15')),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),

  -- Evita cobrança duplicada se o job diário rodar duas vezes
  -- (retry, deploy, falha de rede) — idempotência garantida no banco.
  constraint charges_unico_por_mes unique (contract_id, tipo, mes_referencia)
);

create index charges_contract_id_idx on charges (contract_id);
create index charges_status_idx on charges (status);

create trigger charges_set_updated_at
  before update on charges
  for each row execute function set_updated_at();

-- ============================================================
-- CHARGE_NEGOTIATIONS (resolução de negociação/perdão de multa)
-- ============================================================
create table charge_negotiations (
  id                    uuid primary key default gen_random_uuid(),
  charge_id             uuid not null references charges(id) on delete cascade,
  tipo_resolucao        text check (tipo_resolucao in ('perdao_total', 'desconto_parcial', 'negado')),
  valor_negociado       numeric,
  -- Quem decidiu precisa ser um usuário autenticado real, não texto
  -- livre — "Domingos" digitado à mão não sustenta uma auditoria.
  -- auth.users já existe nativamente em qualquer projeto Supabase.
  decidido_por_user_id  uuid not null references auth.users(id),
  data_decisao          date,
  created_at            timestamptz not null default now()
);

create index charge_negotiations_charge_id_idx on charge_negotiations (charge_id);

-- ============================================================
-- MAINTENANCE_TICKETS
-- ============================================================
create table maintenance_tickets (
  id                  uuid primary key default gen_random_uuid(),
  contract_id         uuid not null references contracts(id) on delete cascade,
  categoria           text not null check (categoria in (
                        'hidraulica', 'eletrica', 'pintura', 'estrutural', 'outros'
                      )),
  urgencia            text not null check (urgencia in ('alta', 'media', 'baixa')),
  descricao           text not null,
  status              text not null default 'aberto' check (status in ('aberto', 'em_andamento', 'resolvido')),
  observacao          text,
  data_abertura       timestamptz not null default now(),
  data_resolucao      timestamptz
);

create index maintenance_tickets_contract_id_idx on maintenance_tickets (contract_id);
create index maintenance_tickets_status_idx on maintenance_tickets (status);

-- ============================================================
-- ESCALATIONS
-- ============================================================
create table escalations (
  id                  uuid primary key default gen_random_uuid(),
  contract_id         uuid not null references contracts(id) on delete cascade,
  motivo              text not null check (motivo in (
                        'sem_clausula', 'pedido_humano', 'rescisao_antecipada',
                        'desconto_renegociacao', 'ameaca_juridica', 'sublocacao_pedido',
                        'troca_fiador', 'obito_fiador', 'risco_estrutural', 'emergencia',
                        'terceiros_condominio', 'loop_nao_resolvido', 'frustracao_crescente',
                        'divergencia_politica_contrato', 'acesso_sem_agendamento',
                        'despesa_responsabilidade_incerta', 'extensao_informal_fora_condicoes',
                        'checkout_vistoria_saida'
                      )),
  descricao           text,
  protocolo           text,
  status              text not null default 'aberto' check (status in ('aberto', 'resolvido')),
  created_at          timestamptz not null default now()
);

create index escalations_contract_id_idx on escalations (contract_id);
create index escalations_status_idx on escalations (status);

-- ============================================================
-- CONTRACT_ALERTS (fluxos A4 — renovação e reajuste)
-- ============================================================
create table contract_alerts (
  id                     uuid primary key default gen_random_uuid(),
  contract_id            uuid not null references contracts(id) on delete cascade,
  tipo                   text not null check (tipo in ('alerta_renovacao_d60', 'calculo_reajuste_d30')),
  data_disparo           date not null,
  percentual_reajuste    numeric,
  valor_sugerido         numeric,
  decisao_gestora        text check (decisao_gestora in ('pendente', 'renovar_sugerido', 'renovar_ajustado', 'encerrar')),
  valor_aplicado         numeric,
  created_at             timestamptz not null default now()
);

create index contract_alerts_contract_id_idx on contract_alerts (contract_id);

-- ============================================================
-- CONVERSATION_LOGS
-- ============================================================
create table conversation_logs (
  id                  uuid primary key default gen_random_uuid(),
  contract_id         uuid not null references contracts(id) on delete cascade,
  remetente           text not null check (remetente in ('inquilino', 'agente', 'gestora')),
  agente_responsavel  text check (agente_responsavel in ('A1', 'A2', 'A3', 'A4', 'A5')),
  mensagem            text not null,
  timestamp           timestamptz not null default now()
);

create index conversation_logs_contract_id_idx on conversation_logs (contract_id);
create index conversation_logs_contract_id_timestamp_idx on conversation_logs (contract_id, timestamp);

-- ============================================================
-- RLS — habilitada e travada (fail-closed) em todas as tabelas.
-- Nenhuma policy ainda: até a Migration 002 rodar, só o
-- service_role acessa essas tabelas. Proposital.
-- ============================================================
alter table contracts            enable row level security;
alter table contract_clauses     enable row level security;
alter table charges               enable row level security;
alter table charge_negotiations  enable row level security;
alter table maintenance_tickets  enable row level security;
alter table escalations           enable row level security;
alter table contract_alerts       enable row level security;
alter table conversation_logs     enable row level security;

