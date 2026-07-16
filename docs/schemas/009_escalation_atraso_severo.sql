-- ============================================================
-- MIGRATION 009 — Novo motivo de escalonamento: atraso_severo
-- ============================================================
-- Depende da Migration 001 já ter rodado (tabela escalations existe).
--
-- Motivação: a lista fechada de 18 motivos de escalations.motivo (Migration
-- 001, ampliada de leitura na Migration 003) não tem nenhum valor que sirva
-- pra "inadimplência chegou em D+15, aciona a gestão automaticamente" — os
-- 13 motivos que o A5 detecta automaticamente (app/agents/a5_escalonamento/
-- criterios.py) são todos disparados a partir de uma MENSAGEM do inquilino;
-- este é o primeiro motivo disparado por um PROCESSO (o cron diário do A2),
-- não por texto de conversa — daí não fazer sentido incluí-lo no critério
-- que o Claude do A5 avalia por mensagem (ver app/agents/a5_escalonamento/
-- criterios.py e escalonamento.py, campo deteccao_via_mensagem=False).
--
-- Esta migration só abre espaço no schema para o valor novo. Quem de fato
-- decide "este contrato específico chegou em D+15, chamar
-- executar_escalonamento(contract_id, motivo='atraso_severo', ...)" é a
-- lógica de negócio do Agente 2 (app/agents/a2_cobranca/), ainda não
-- implementada — fora do escopo desta migration.
--
-- A constraint de escalations.motivo foi criada SEM NOME explícito na
-- Migration 001 (`check (motivo in (...))`), então o Postgres gerou um nome
-- automático (convenção: escalations_motivo_check). Em vez de assumir esse
-- nome às cegas, o bloco abaixo descobre o nome real via pg_constraint
-- antes de derrubar — mais seguro caso o nome automático tenha saído
-- diferente do esperado em algum ambiente.
-- ============================================================

do $$
declare
  v_constraint_name text;
begin
  select conname into v_constraint_name
  from pg_constraint
  where conrelid = 'escalations'::regclass
    and contype = 'c'
    and pg_get_constraintdef(oid) like '%motivo%';

  if v_constraint_name is not null then
    execute format('alter table escalations drop constraint %I', v_constraint_name);
  end if;
end
$$;

alter table escalations add constraint escalations_motivo_check check (motivo in (
  'sem_clausula', 'pedido_humano', 'rescisao_antecipada',
  'desconto_renegociacao', 'ameaca_juridica', 'sublocacao_pedido',
  'troca_fiador', 'obito_fiador', 'risco_estrutural', 'emergencia',
  'terceiros_condominio', 'loop_nao_resolvido', 'frustracao_crescente',
  'divergencia_politica_contrato', 'acesso_sem_agendamento',
  'despesa_responsabilidade_incerta', 'extensao_informal_fora_condicoes',
  'checkout_vistoria_saida',
  'atraso_severo'
));

-- ============================================================
-- FIM DA MIGRATION 009
-- ============================================================
