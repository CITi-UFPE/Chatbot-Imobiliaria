-- ============================================================
-- MIGRATION 019 — Normalização brasileira de telefone
-- ============================================================
-- Depende das Migrations 001 e 004.
--
-- Mantém resolver_contrato_por_telefone(text) -> uuid|null e o acesso pelo
-- papel anon. Não altera telefone_whatsapp nem usa service_role: as formas
-- equivalentes são calculadas para indexação e consulta.
-- ============================================================

begin;

-- Formas aceitas: DDD+número ou 55+DDD+número, com apresentação opcional.
-- A primeira posição do array é sempre a forma canônica atual. O nono
-- dígito só é inserido/removido imediatamente depois do DDD e somente para
-- prefixos móveis (6-9 na numeração legada). Fixos 2-5 não ganham variante.
create or replace function public.telefone_br_candidatos(p_telefone text)
returns text[]
language plpgsql
immutable
strict
parallel safe
as $$
declare
  v_digitos text;
  v_nacional text;
  v_ddd text;
  v_assinante text;
  v_prefixo text;
begin
  if btrim(p_telefone) = ''
     or btrim(p_telefone) !~ '^\+?[0-9(). -]+$' then
    return array[]::text[];
  end if;

  v_digitos := regexp_replace(btrim(p_telefone), '[^0-9]', '', 'g');

  if length(v_digitos) in (12, 13) then
    if left(v_digitos, 2) <> '55' then
      return array[]::text[];
    end if;
    v_nacional := substr(v_digitos, 3);
  elsif length(v_digitos) in (10, 11) then
    v_nacional := v_digitos;
  else
    return array[]::text[];
  end if;

  v_ddd := left(v_nacional, 2);
  v_assinante := substr(v_nacional, 3);
  if length(v_ddd) <> 2 or left(v_ddd, 1) = '0' then
    return array[]::text[];
  end if;

  v_prefixo := '55' || v_ddd;
  if length(v_assinante) = 8 then
    if left(v_assinante, 1) between '2' and '5' then
      return array[v_prefixo || v_assinante];
    elsif left(v_assinante, 1) between '6' and '9' then
      return array[v_prefixo || '9' || v_assinante, v_prefixo || v_assinante];
    end if;
  elsif length(v_assinante) = 9
        and left(v_assinante, 1) = '9'
        and substr(v_assinante, 2, 1) between '6' and '9' then
    return array[v_prefixo || v_assinante, v_prefixo || substr(v_assinante, 2)];
  end if;

  return array[]::text[];
end;
$$;

-- Uma única chave por telefone: móveis atuais e legados convergem para a
-- forma atual; fixos permanecem inalterados. NULL representa entrada inválida.
create or replace function public.telefone_br_chave(p_telefone text)
returns text
language sql
immutable
strict
parallel safe
as $$
  select (public.telefone_br_candidatos(p_telefone))[1];
$$;

-- Falhar antes de criar o índice produz um diagnóstico claro e não escolhe
-- silenciosamente qual contrato manter. A transação inteira é revertida para
-- que a migration possa ser reaplicada depois do saneamento dos dados.
do $$
begin
  if exists (
    select 1
    from public.contracts
    where status in ('ativo', 'pendente_confirmacao')
      and public.telefone_br_chave(telefone_whatsapp) is not null
    group by public.telefone_br_chave(telefone_whatsapp)
    having count(*) > 1
  ) then
    raise exception using
      errcode = '23505',
      message = 'Existem contratos ativos ou pendentes com telefones brasileiros equivalentes; saneie os dados antes de aplicar a Migration 019.';
  end if;
end;
$$;

-- Inativos são históricos e não bloqueiam um novo cadastro. Ativos e
-- pendentes são operacionais: a segunda inserção/ativação equivalente falha
-- imediatamente com unique_violation, antes de qualquer mensagem chegar.
create unique index if not exists contracts_telefone_normalizado_operacional_uidx
  on public.contracts (public.telefone_br_chave(telefone_whatsapp))
  where status in ('ativo', 'pendente_confirmacao')
    and public.telefone_br_chave(telefone_whatsapp) is not null;

create or replace function public.resolver_contrato_por_telefone(p_telefone text)
returns uuid
language plpgsql
security definer
stable
set search_path = ''
as $$
declare
  v_chave text;
  v_ids uuid[];
begin
  v_chave := public.telefone_br_chave(p_telefone);
  if v_chave is null then
    return null;
  end if;

  select array_agg(id order by id)
  into v_ids
  from (
    select id
    from public.contracts
    where status = 'ativo'
      and public.telefone_br_chave(telefone_whatsapp) = v_chave
    limit 2
  ) correspondencias;

  if coalesce(cardinality(v_ids), 0) > 1 then
    raise exception using
      errcode = 'P0001',
      message = 'Inconsistência: mais de um contrato ativo corresponde ao telefone normalizado.';
  end if;

  return v_ids[1];
end;
$$;

revoke all on function public.resolver_contrato_por_telefone(text) from public;
grant execute on function public.resolver_contrato_por_telefone(text) to anon;

comment on function public.telefone_br_candidatos(text) is
  'Gera candidatos brasileiros controlados com país 55 e variante móvel com/sem nono dígito.';
comment on function public.telefone_br_chave(text) is
  'Chave canônica brasileira usada para unicidade e resolução de contratos por telefone.';
comment on function public.resolver_contrato_por_telefone(text) is
  'Retorna o UUID do único contrato ativo correspondente ao telefone normalizado, null sem match e erro em inconsistência.';

commit;

-- ============================================================
-- FIM DA MIGRATION 019
-- ============================================================
