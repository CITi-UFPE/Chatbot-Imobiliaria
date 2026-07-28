-- ============================================================
-- MIGRATION 012 — Água individualizada por contrato
-- ============================================================
-- Depende da Migration 001 (tabelas contracts/charges) já ter rodado.
--
-- Problema: nem todo imóvel tem hidrômetro individual. Em vários
-- contratos o valor da água já vem embutido no condomínio, e a
-- cobrança de água (charges.tipo = 'agua') lançada mensalmente pela
-- gestora em AguaSection.tsx não deveria existir para esses casos —
-- cobraria a água duas vezes (uma dentro do condomínio, outra à
-- parte).
--
-- Decisão de negócio (alinhada com a gestora): o campo é definido
-- manualmente na criação do contrato, nunca inferido pela extração
-- por IA — esse campo tem efeito financeiro direto (gera ou não uma
-- cobrança separada todo mês) e o texto do contrato nem sempre deixa
-- isso explícito o suficiente para a IA acertar com segurança. Editar
-- o campo depois que o contrato já existe fica fora do escopo desta
-- migration (ver issue #19 — hoje só é possível via acesso direto ao
-- banco).
--
-- Default 'false': mais seguro nascer sem gerar cobrança separada
-- (água embutida no condomínio) do que nascer cobrando em duplicidade
-- — mesmo raciocínio "fail-closed" das Migrations 001/002. Contratos
-- já cadastrados antes desta migration também recebem 'false' — se
-- algum deles já tiver hidrômetro individual de fato, a gestora precisa
-- ativar manualmente (não dá pra inferir isso a partir do que já está
-- no banco).
-- ------------------------------------------------------------
alter table contracts
  add column if not exists agua_individualizada boolean not null default false;

comment on column contracts.agua_individualizada is
  'Se true, o imóvel tem hidrômetro individual e a água é cobrada separadamente (charges.tipo = ''agua''). Se false (padrão), o valor da água já está embutido no condomínio — nenhuma charge tipo agua deve ser gerada (reforçado pelo trigger charges_valida_agua_individualizada). Definido manualmente pela gestora na criação do contrato; a extração por IA não preenche este campo. Editar depois da criação ainda não tem tela própria — ver issue #19.';

-- ------------------------------------------------------------
-- Trava no banco (mesma doutrina da Migration 002: "a trava está no
-- banco, não no código da aplicação") — além do filtro em
-- AguaSection.tsx (que nem lista o contrato pra lançamento de
-- leitura quando agua_individualizada = false), qualquer INSERT ou
-- UPDATE em charges com tipo = 'agua' é bloqueado no banco se o
-- contrato correspondente não tiver água individualizada. Isso
-- protege contra qualquer caminho de escrita futuro (script, nova
-- automação, cron de geração de cobrança ainda não implementado) que
-- não passe pelo filtro do frontend.
-- ------------------------------------------------------------
create or replace function check_agua_individualizada()
returns trigger
language plpgsql
as $$
declare
  v_individualizada boolean;
begin
  select agua_individualizada into v_individualizada
  from contracts
  where id = new.contract_id;

  if v_individualizada is not true then
    raise exception
      'contrato % está com agua_individualizada=false — água embutida no condomínio, não é permitido gerar charge tipo agua para ele',
      new.contract_id;
  end if;

  return new;
end;
$$;

drop trigger if exists charges_valida_agua_individualizada on charges;

create trigger charges_valida_agua_individualizada
  before insert or update on charges
  for each row
  when (new.tipo = 'agua')
  execute function check_agua_individualizada();

-- ============================================================
-- FIM DA MIGRATION 012
-- ============================================================
