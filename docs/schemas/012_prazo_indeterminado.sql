-- ============================================================
-- MIGRATION 012 — Prazo indeterminado (Projeto Domingos)
-- ============================================================
-- Origem: contrato do Elias (Sala Ubaias) já passou de data_termino e,
-- pela cláusula 3.3, se renova automaticamente por inércia — ou seja,
-- não há mais uma data de término real prevista.
--
-- contracts.data_termino é "not null check (data_termino > data_inicio)"
-- desde a Migration 001 — não existe hoje forma de representar "sem
-- término". Zerar/anular essa coluna NÃO é opção: o Fluxo A do A4
-- (app/tools/calculo_reajuste.py::esta_na_janela_alerta_renovacao) faz
-- `data_termino - hoje`, e isso quebra com TypeError se data_termino for
-- NULL — quebraria o job diário pra TODOS os contratos, não só o do
-- Elias, porque o cron roda em lote.
--
-- Solução: coluna aditiva. data_termino continua preenchida (mantém a
-- data antiga/original do contrato, agora só decorativa pra esse caso),
-- e prazo_indeterminado=true faz o Fluxo A pular esse contrato
-- deliberadamente (ver ajuste em
-- app/agents/a4_gestao_contratual/fluxo.py::processar_alerta_renovacao).
-- Fluxo B (reajuste, baseado no aniversário de data_inicio) não é afetado
-- — reajuste anual continua fazendo sentido mesmo sem data de término.
-- ============================================================

alter table contracts
  add column if not exists prazo_indeterminado boolean not null default false;

comment on column contracts.prazo_indeterminado is
  'true = contrato renovado por inércia/prazo indeterminado (ex: cláusula 3.3). data_termino permanece preenchida (valor histórico, não usado para decisão) mas o Fluxo A do A4 (alerta de renovação D-60) ignora esses contratos — ver docs/schemas/012_prazo_indeterminado.sql e app/agents/a4_gestao_contratual/fluxo.py.';

-- cron_listar_contratos_ativos (Migration 010) precisa devolver esse
-- campo pro A4 decidir se pula o Fluxo A — create or replace preserva o
-- GRANT EXECUTE já concedido a cron_batch, não precisa reconceder.
create or replace function cron_listar_contratos_ativos()
returns table (
  id                  uuid,
  imovel_identificacao text,
  inquilino_nome      text,
  telefone_whatsapp   text,
  data_inicio         date,
  data_termino        date,
  indice_reajuste     text,
  valor_aluguel       numeric,
  prazo_indeterminado boolean
)
language sql
security definer
stable
as $$
  select id, imovel_identificacao, inquilino_nome, telefone_whatsapp,
         data_inicio, data_termino, indice_reajuste, valor_aluguel,
         prazo_indeterminado
  from contracts
  where status = 'ativo';
$$;

-- ============================================================
-- FIM DA MIGRATION 012
-- ============================================================
