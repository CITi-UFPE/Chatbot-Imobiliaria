-- ============================================================
-- MIGRATION 027 — alterar o vencimento de cobranças atrasadas (com auditoria)
-- ============================================================
-- Depende das Migrations 001 e 002 (charges, is_staff()).
--
-- Pedido do cliente (30/10/2026): poder editar as contas vencidas informando
-- uma nova data de vencimento. Dois objetos:
--
--   charge_vencimento_changes — trilha de auditoria: data anterior, data nova,
--     status antes/depois e quem alterou. Só a RPC grava; a staff só lê;
--     ninguém atualiza nem apaga (a trilha é imutável pelo app).
--
--   alterar_vencimento_charge(p_charge_id, p_nova_data) — altera
--     charges.data_vencimento de UMA cobrança 'atrasado' e grava a auditoria na
--     mesma transação (uma sem a outra não acontece).
--
-- Regras da RPC:
--   - só a staff (is_staff()); a cobrança precisa estar 'atrasado'; a data nova
--     precisa ser diferente da atual;
--   - dias_atraso e status são recalculados com "hoje" no fuso do projeto:
--     dias > 0 -> 'atrasado'; senão -> 'pendente'. O cron do A2 nunca devolve
--     'atrasado' para 'pendente' (cobranca.py: novo_status só sobe pra
--     'atrasado'), então sem isto uma data futura deixaria o painel e o bot A1
--     dizendo "em atraso" numa conta que ainda não venceu;
--   - mensagem_estagio NÃO é alterado de propósito: com data nova futura o cron
--     retoma d-5/d0/d+5/d+10 normalmente (todos diferem do 'd+15' salvo); com
--     data nova ainda passada há 15+ dias, zerar o estágio dispararia um "atraso
--     severo" imediato e uma nova escalação.
--
-- Aplicar ANTES de subir o frontend que chama a RPC.
-- ============================================================

begin;

create table if not exists charge_vencimento_changes (
  id                    uuid primary key default gen_random_uuid(),
  charge_id             uuid not null references charges(id) on delete cascade,
  data_anterior         date not null,
  data_nova             date not null,
  status_anterior       text not null,
  status_novo           text not null,
  alterado_por_user_id  uuid not null references auth.users(id),
  created_at            timestamptz not null default now()
);

create index if not exists charge_vencimento_changes_charge_id_idx
  on charge_vencimento_changes (charge_id, created_at);

alter table charge_vencimento_changes enable row level security;

-- Staff só lê. Escrita: apenas a RPC abaixo (security definer).
drop policy if exists staff_read_all on charge_vencimento_changes;
create policy staff_read_all on charge_vencimento_changes
  for select using (is_staff());

revoke all on charge_vencimento_changes from anon, authenticated;
grant select on charge_vencimento_changes to authenticated;

create or replace function public.alterar_vencimento_charge(
  p_charge_id uuid,
  p_nova_data date
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_charge  public.charges%rowtype;
  v_hoje    date := (now() at time zone 'America/Sao_Paulo')::date;
  v_dias    integer;
  v_status  text;
begin
  if not public.is_staff() then
    raise exception 'Apenas a equipe pode alterar o vencimento de uma cobrança.'
      using errcode = '42501';
  end if;

  if p_nova_data is null then
    raise exception 'Informe a nova data de vencimento.' using errcode = '22023';
  end if;

  -- Trava a linha: o cron do A2 também atualiza charges.
  select * into v_charge from public.charges where id = p_charge_id for update;

  if not found then
    raise exception 'Cobrança não encontrada.' using errcode = 'P0002';
  end if;

  if v_charge.status <> 'atrasado' then
    raise exception 'Só é possível alterar o vencimento de uma cobrança atrasada (status atual: %).',
      v_charge.status using errcode = '22023';
  end if;

  if v_charge.data_vencimento = p_nova_data then
    raise exception 'A nova data é igual ao vencimento atual.' using errcode = '22023';
  end if;

  v_dias := v_hoje - p_nova_data;
  v_status := case when v_dias > 0 then 'atrasado' else 'pendente' end;

  update public.charges
     set data_vencimento = p_nova_data,
         dias_atraso     = v_dias,
         status          = v_status
   where id = p_charge_id;

  insert into public.charge_vencimento_changes (
    charge_id, data_anterior, data_nova, status_anterior, status_novo, alterado_por_user_id
  ) values (
    p_charge_id, v_charge.data_vencimento, p_nova_data, v_charge.status, v_status, auth.uid()
  );

  return jsonb_build_object('status', v_status, 'dias_atraso', v_dias);
end;
$$;

revoke all on function public.alterar_vencimento_charge(uuid, date) from public;
revoke all on function public.alterar_vencimento_charge(uuid, date) from anon;
grant execute on function public.alterar_vencimento_charge(uuid, date) to authenticated;

comment on function public.alterar_vencimento_charge(uuid, date) is
  'Altera o vencimento de uma cobrança atrasada (só staff), recalcula dias_atraso/status e grava a auditoria na mesma transação. Não mexe em mensagem_estagio.';

commit;

-- ============================================================
-- FIM DA MIGRATION 027
-- ============================================================
