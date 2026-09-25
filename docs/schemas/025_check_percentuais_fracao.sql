-- ============================================================
-- MIGRATION 025 — check constraint em multa_moratoria_percentual e
-- juros_moratorio_mensal (garante fração, nunca percentual inteiro)
-- ============================================================
-- Motivação: encontrado em produção um contrato (SAULO BANDEIRA DURVAL,
-- Edifício Golden Beach) com multa_moratoria_percentual = 10 em vez de
-- 0.10 — valor que faz o cálculo de "valor atualizado" na tela de
-- Cobranças (frontend/src/components/gestao/CobrancasSection.tsx)
-- explodir (ex: R$2.000,00 virando R$22.000,67 com 1 dia de atraso).
--
-- Essa ambiguidade (fração vs. percentual inteiro) já era um risco
-- CONHECIDO e documentado desde a Migration 003 (comentário na própria
-- coluna) e reforçado na Migration 011 (comment em
-- docs/schemas/011_a2_cobranca_rpcs.sql) — mas nunca ganhou uma trava de
-- verdade, nem no schema de extração (app/models/contract.py,
-- ContratoExtraido não tinha ge/le nesses dois campos, diferente dos
-- campos vizinhos como multa_infracao_valor), nem no banco (essa tabela
-- tem `check` em várias colunas irmãs, mas não nestas duas), nem na
-- revisão manual (Passo 3 do formulário de contrato no frontend nem
-- mostra esses dois campos pra equipe conferir antes de salvar).
--
-- Esta migration fecha a camada mais robusta das três: um `check` no
-- banco protege contra QUALQUER caminho de escrita errado — extração via
-- LLM, edição manual pelo SQL Editor (como o próprio Davi precisou fazer
-- pra corrigir o Saulo) ou um futuro formulário no frontend. As outras
-- duas camadas (Pydantic + frontend) estão em app/models/contract.py e
-- ContratosSection.tsx, tratadas separadamente.
--
-- Teto escolhido: < 1 (100%). Não usamos algo mais apertado tipo < 0.2
-- porque o objetivo aqui é só barrar o erro óbvio de dígito (10 em vez
-- de 0.10) sem arriscar rejeitar algum caso real de contrato com multa
-- alta que a gente ainda não previu.
-- ============================================================

begin;

alter table public.contracts
  add constraint contracts_multa_moratoria_percentual_fracao
  check (multa_moratoria_percentual is null or multa_moratoria_percentual < 1);

alter table public.contracts
  add constraint contracts_juros_moratorio_mensal_fracao
  check (juros_moratorio_mensal < 1);

comment on constraint contracts_multa_moratoria_percentual_fracao on public.contracts is
  'Garante que o valor é uma fração decimal (ex: 0.10 = 10%), nunca um percentual inteiro (10) — ver docs/schemas/025_check_percentuais_fracao.sql para o bug real que motivou isso.';

comment on constraint contracts_juros_moratorio_mensal_fracao on public.contracts is
  'Mesma trava de contracts_multa_moratoria_percentual_fracao, aplicada a juros_moratorio_mensal.';

commit;

-- ============================================================
-- FIM DA MIGRATION 025
-- ============================================================
