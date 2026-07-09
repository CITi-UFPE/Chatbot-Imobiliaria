-- ============================================================
-- MIGRATION 003 — Ajustes pós-revisão (Projeto Domingos)
-- ============================================================
-- Depende das Migrations 001 e 002 já terem rodado.
--
-- Origem: revisão de uma colega de time comparando o schema com os
-- 8 contratos reais. Dois problemas encontrados:
--
--  1) Categorias de cláusula insuficientes — cláusulas como objeto
--     do contrato, prazo/vigência, alienação (direito de
--     preferência), desapropriação e foro não tinham categoria
--     própria e estavam sendo forçadas em "rescisao", o que é
--     semanticamente errado e arrisca o A4 puxar a cláusula errada
--     numa consulta filtrada por categoria.
--
--  2) Campos de endereço do locatário e do fiador não existiam —
--     só tínhamos o endereço do imóvel alugado. Endereço residencial
--     importa para notificação formal (cobrança judicial,
--     escalonamento via A5).
--
-- Barato agora (zero dados reais carregados ainda), caro depois
-- (exigiria re-categorizar cláusulas já inseridas).
-- ============================================================

-- ------------------------------------------------------------
-- 3.1 — Novas categorias de cláusula
--
-- prazo_vigencia: duração, prorrogação, holdover (inquilino que
--   continua após o prazo). Uso direto do A4.
-- alienacao: direito de preferência do inquilino se o imóvel for
--   vendido. Uso direto do A4.
-- disposicoes_gerais: catch-all para objeto do contrato, foro,
--   desapropriação, fechamento — cláusulas de baixo uso pelos
--   agentes, mas que não deveriam contaminar "rescisao".
--
-- Constraint original era um CHECK inline sem nome explícito, então
-- localizamos o nome real gerado pelo Postgres em vez de assumir a
-- convenção padrão — mais seguro caso algo tenha sido renomeado.
-- ------------------------------------------------------------
do $$
declare
  v_constraint_name text;
begin
  select con.conname into v_constraint_name
  from pg_constraint con
  join pg_class rel on rel.oid = con.conrelid
  where rel.relname = 'contract_clauses'
    and con.contype = 'c'
    and pg_get_constraintdef(con.oid) like '%categoria%';

  if v_constraint_name is not null then
    execute format('alter table contract_clauses drop constraint %I', v_constraint_name);
  end if;
end
$$;

alter table contract_clauses add constraint contract_clauses_categoria_check
  check (categoria in (
    'financeiro', 'benfeitorias', 'sublocacao', 'vistoria',
    'conservacao', 'agua_energia', 'fiador', 'rescisao', 'multa',
    'prazo_vigencia', 'alienacao', 'disposicoes_gerais'
  ));

-- ------------------------------------------------------------
-- 3.2 — Endereço residencial do locatário e do fiador
--
-- Nullable: nem todo contrato tem fiador (pode ser caução), e
-- contratos já confirmados sem esse dado não devem quebrar.
-- ------------------------------------------------------------
alter table contracts
  add column if not exists locatario_endereco text,
  add column if not exists fiador_endereco text;

-- ------------------------------------------------------------
-- 3.3 — Correção de contexto: ARCO NÃO é isento de multa moratória
--
-- O comentário original da Migration 001 dizia "NULL para ARCO
-- (isento de multa, só juros)" — isso estava errado. A cláusula
-- 14.1 do contrato do ARCO chama expressamente o que está na
-- cláusula 5.1 de "a multa moratória", confirmando que ela existe.
--
-- O que ainda fica pendente de confirmação humana: a cláusula 5.1
-- agrupa "juros e multa moratória" numa única "base de 1% a.m." —
-- ambíguo se é uma taxa combinada de 1% ou duas taxas empilhadas de
-- 1% cada (juros + multa = 2%). Como já existe um default de 0.01
-- em juros_moratorio_mensal, preencher multa_moratoria_percentual
-- também com 0.01 sem confirmar pode fazer o sistema cobrar o
-- dobro do que o contrato realmente prevê.
--
-- Por isso o comentário fica registrado direto na coluna do banco
-- (visível em qualquer client, não só em quem lê o arquivo .sql) —
-- e o contrato do ARCO deve entrar com status='pendente_confirmacao'
-- até essa dúvida ser resolvida com o Domingos.
-- ------------------------------------------------------------
comment on column contracts.multa_moratoria_percentual is
  'ARCO: cláusula 5.1 agrupa "juros e multa moratória" em base de 1% a.m. — ambíguo se é 1% combinado ou 1%+1% (2%) empilhado com juros_moratorio_mensal. PENDENTE confirmação com o Domingos antes de carregar os dados do ARCO. Ver docs/schemas/001_create_tables.sql e 003_ajusta_categorias_clausulas.sql.';

-- ============================================================
-- FIM DA MIGRATION 003
-- ============================================================
