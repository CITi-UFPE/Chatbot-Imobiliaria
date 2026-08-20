-- ============================================================
-- MIGRATION 018 — Garantia por aluguel antecipado (Projeto Domingos)
-- ============================================================
-- Origem: contrato do Apto 1304 travava na extração (Pydantic
-- ValidationError, HTTP 500 antes de chegar na tela de revisão). O
-- binário garantia_tipo IN ('fiador', 'caucao') não tem onde encaixar um
-- contrato sem fiador em que o locatário pagou meses de aluguel
-- ADIANTADOS (ex: 1º + último mês, R$12.000,00) como garantia, em vez de
-- uma caução clássica retida à parte. O modelo de extração sinalizou a
-- ambiguidade corretamente em vez de inventar um valor (comportamento
-- esperado do SYSTEM_PROMPT) — mas isso trava o cadastro inteiro sem
-- nenhuma forma de correção manual na UI, porque o erro acontece antes do
-- Passo 2 do wizard existir.
--
-- Solução: terceiro valor aditivo pra garantia_tipo. Puramente aditivo —
-- 'fiador' e 'caucao' continuam com a mesma obrigatoriedade de sempre,
-- nenhum contrato já cadastrado muda de estado, não precisa repopular
-- nada. garantia_valor passa a ser obrigatório também para
-- 'aluguel_antecipado' (mesmo racional de 'caucao': é o valor total pago
-- adiantado, um dado real e útil, só a natureza jurídica é diferente).
-- ============================================================

-- Check inline da coluna (nome default do Postgres pra "check (coluna in (...))"
-- declarado sem nome próprio na criação da tabela: <tabela>_<coluna>_check).
alter table contracts drop constraint if exists contracts_garantia_tipo_check;
alter table contracts add constraint contracts_garantia_tipo_check
  check (garantia_tipo in ('fiador', 'caucao', 'aluguel_antecipado'));

-- Check nomeado (Migration 001) que amarra garantia_tipo aos campos que
-- ela exige preenchidos.
alter table contracts drop constraint if exists garantia_coerente;
alter table contracts add constraint garantia_coerente check (
  (garantia_tipo = 'fiador' and fiador_nome is not null and fiador_cpf is not null)
  or
  (garantia_tipo in ('caucao', 'aluguel_antecipado') and garantia_valor is not null)
);

comment on column contracts.garantia_valor is
  'Obrigatório se garantia_tipo = caucao (valor retido) ou aluguel_antecipado (total de meses pagos adiantados como garantia, sem retenção formal).';

-- ============================================================
-- FIM DA MIGRATION 018
-- ============================================================
