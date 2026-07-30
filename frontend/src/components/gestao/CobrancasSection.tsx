import { useState } from "react";
import { toast } from "sonner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, HandCoins, Wallet } from "lucide-react";
import { PageHeader } from "./PageHeader";
import { StatTile } from "./StatTile";
import { Avatar } from "./Avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { supabase } from "@/lib/supabase";
import type { TipoResolucaoNegociacao } from "@/lib/database.types";

const COBRANCAS_QUERY_KEY = ["charges-em-negociacao"] as const;
const ATRASADAS_QUERY_KEY = ["charges-em-atraso"] as const;

type Tipo = "" | "total" | "parcial" | "negado";

const TIPO_TO_RESOLUCAO: Record<Exclude<Tipo, "">, TipoResolucaoNegociacao> = {
  total: "perdao_total",
  parcial: "desconto_parcial",
  negado: "negado",
};

// Linha vinda de charges + o contrato relacionado (join), já achatada pra UI.
interface Negociacao {
  chargeId: string;
  contractId: string;
  inquilino: string;
  imovel: string;
  telefone: string | null;
  mes: string; // formatado a partir de mes_referencia
  valor: number;
}

// Linha de charge em atraso (status='atrasado'), com o valor final já
// calculado (inicial + multa + juros) seguindo a MESMA fórmula de
// app/agents/a2_cobranca/mensagens.py:_calcular_encargos — precisa manter
// as duas em sincronia se a fórmula mudar de um lado.
interface Atraso {
  chargeId: string;
  contractId: string;
  inquilino: string;
  imovel: string;
  telefone: string | null;
  mes: string;
  diasAtraso: number;
  valorInicial: number;
  valorFinal: number;
}

async function fetchNegociacoes(): Promise<Negociacao[]> {
  const { data, error } = await supabase
    .from("charges")
    .select(
      "id, contract_id, mes_referencia, valor_esperado, contracts(inquilino_nome, imovel_endereco, telefone_whatsapp)",
    )
    .eq("status", "em_negociacao")
    .order("mes_referencia", { ascending: false });

  if (error) throw error;

  return (data ?? []).map((row: any) => ({
    chargeId: row.id,
    contractId: row.contract_id,
    inquilino: row.contracts?.inquilino_nome ?? "—",
    imovel: row.contracts?.imovel_endereco ?? "—",
    telefone: row.contracts?.telefone_whatsapp ?? null,
    mes: new Date(row.mes_referencia).toLocaleDateString("pt-BR", {
      month: "long",
      year: "numeric",
    }),
    valor: Number(row.valor_esperado),
  }));
}

// Mesma convenção assumida em mensagens.py: multa_moratoria_percentual é
// fração (0.02 = 2%), não percentual inteiro. Juros prorateado num mês de
// 30 dias. Ver nota de unidade ainda pendente na Migration 011/003 — se a
// convenção mudar de um lado, precisa mudar dos dois.
function calcularValorFinal(
  valorEsperado: number,
  diasAtraso: number,
  multaPercentual: number | null,
  jurosMensal: number,
): number {
  const percentualMulta = multaPercentual ?? 0;
  const valorMulta = valorEsperado * percentualMulta;
  const valorJuros = valorEsperado * jurosMensal * (diasAtraso / 30);
  return valorEsperado + valorMulta + valorJuros;
}

async function fetchAtrasadas(): Promise<Atraso[]> {
  const { data, error } = await supabase
    .from("charges")
    .select(
      "id, contract_id, mes_referencia, valor_esperado, dias_atraso, contracts(inquilino_nome, imovel_endereco, telefone_whatsapp, multa_moratoria_percentual, juros_moratorio_mensal)",
    )
    .eq("status", "atrasado")
    .order("dias_atraso", { ascending: false });

  if (error) throw error;

  return (data ?? []).map((row: any) => {
    const valorEsperado = Number(row.valor_esperado);
    const diasAtraso = Number(row.dias_atraso ?? 0);
    return {
      chargeId: row.id,
      contractId: row.contract_id,
      inquilino: row.contracts?.inquilino_nome ?? "—",
      imovel: row.contracts?.imovel_endereco ?? "—",
      telefone: row.contracts?.telefone_whatsapp ?? null,
      mes: new Date(row.mes_referencia).toLocaleDateString("pt-BR", {
        month: "long",
        year: "numeric",
      }),
      diasAtraso,
      valorInicial: valorEsperado,
      valorFinal: calcularValorFinal(
        valorEsperado,
        diasAtraso,
        row.contracts?.multa_moratoria_percentual ?? null,
        row.contracts?.juros_moratorio_mensal ?? 0,
      ),
    };
  });
}

// Estado local só do formulário de resolução (tipo escolhido, valor digitado)
// — não é dado do banco, por isso continua em useState em vez de query.
interface FormState {
  tipo: Tipo;
  valorNegociado: string;
}

// Estado local do formulário de "Marcar como Pago" (data e valor
// efetivamente recebidos) — também não é dado do banco, mora em useState.
// Data default = hoje (editável); valor default = valorFinal calculado
// (editável, é só um chute inicial pra poupar digitação).
interface PagamentoFormState {
  dataPagamento: string;
  valorPago: string;
}

function hojeISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function AtrasoCard({
  n,
  isPending,
  form,
  onChangeForm,
  onMarcarPago,
}: {
  n: Atraso;
  isPending: boolean;
  form: PagamentoFormState;
  onChangeForm: (patch: Partial<PagamentoFormState>) => void;
  onMarcarPago: () => void;
}) {
  const valorInvalido = form.valorPago !== "" && Number(form.valorPago) <= 0;

  return (
    <Card key={n.chargeId}>
      <CardHeader className="flex flex-row items-start justify-between space-y-0">
        <div className="flex items-center gap-3">
          <Avatar name={n.inquilino} size={36} />
          <div>
            <CardTitle className="text-base">{n.inquilino}</CardTitle>
            <p className="text-sm text-muted-foreground mt-1">{n.imovel}</p>
          </div>
        </div>
        <Badge variant="outline">{n.diasAtraso} dias em atraso</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-xs uppercase text-muted-foreground">Mês de Referência</div>
            <div className="font-medium">{n.mes}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted-foreground">Valor Original</div>
            <div className="font-medium tnum">
              R$ {n.valorInicial.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted-foreground">Valor Atualizado (hoje)</div>
            <div className="font-semibold text-lg tnum">
              R$ {n.valorFinal.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted-foreground">Telefone</div>
            <div className="font-medium">
              {n.telefone ?? <span className="text-muted-foreground italic">Não Registrado</span>}
            </div>
          </div>
        </div>

        <div className="grid sm:grid-cols-[1fr,1fr,auto] gap-3 items-end pt-2 border-t">
          <div className="space-y-1.5">
            <Label>Data do Pagamento</Label>
            <Input
              type="date"
              value={form.dataPagamento}
              onChange={(e) => onChangeForm({ dataPagamento: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Valor Pago (R$)</Label>
            <Input
              type="number"
              step="0.01"
              placeholder="0,00"
              value={form.valorPago}
              onChange={(e) => onChangeForm({ valorPago: e.target.value })}
              aria-invalid={valorInvalido}
            />
          </div>
          <Button
            onClick={onMarcarPago}
            disabled={isPending || !form.dataPagamento || !form.valorPago || valorInvalido}
          >
            {isPending ? "Confirmando..." : "Marcar como Pago"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function CobrancasSection() {
  const queryClient = useQueryClient();
  const [forms, setForms] = useState<Record<string, FormState>>({});
  const [pagamentoForms, setPagamentoForms] = useState<Record<string, PagamentoFormState>>({});

  const { data: items = [], isLoading, isError } = useQuery({
    queryKey: COBRANCAS_QUERY_KEY,
    queryFn: fetchNegociacoes,
  });

  const {
    data: atrasadas = [],
    isLoading: isLoadingAtrasadas,
    isError: isErrorAtrasadas,
  } = useQuery({
    queryKey: ATRASADAS_QUERY_KEY,
    queryFn: fetchAtrasadas,
  });

  const atrasadasLeves = atrasadas.filter((a) => a.diasAtraso <= 14);
  const atrasadasCriticas = atrasadas.filter((a) => a.diasAtraso >= 15);

  const getForm = (id: string): FormState => forms[id] ?? { tipo: "", valorNegociado: "" };
  const updateForm = (id: string, patch: Partial<FormState>) =>
    setForms((prev) => ({ ...prev, [id]: { ...getForm(id), ...patch } }));

  // valorFinal só existe depois que "atrasadas" carrega, por isso o default
  // do valor pago é aplicado sob demanda (getPagamentoForm), não no useState inicial.
  const getPagamentoForm = (n: Atraso): PagamentoFormState =>
    pagamentoForms[n.chargeId] ?? {
      dataPagamento: hojeISO(),
      valorPago: n.valorFinal.toFixed(2),
    };
  const updatePagamentoForm = (n: Atraso, patch: Partial<PagamentoFormState>) =>
    setPagamentoForms((prev) => ({
      ...prev,
      [n.chargeId]: { ...getPagamentoForm(n), ...patch },
    }));

  const resolverMutation = useMutation({
    mutationFn: async (n: Negociacao) => {
      const form = getForm(n.chargeId);
      if (!form.tipo) throw new Error("Selecione o tipo de resolução");
      if (form.tipo === "parcial" && !form.valorNegociado)
        throw new Error("Informe o valor negociado");

      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) throw new Error("Sessão expirada — faça login novamente");

      const valorNegociado = form.tipo === "parcial" ? Number(form.valorNegociado) : null;

      const { error: negotiationError } = await supabase.from("charge_negotiations").insert({
        charge_id: n.chargeId,
        tipo_resolucao: TIPO_TO_RESOLUCAO[form.tipo as Exclude<Tipo, "">],
        valor_negociado: valorNegociado,
        decidido_por_user_id: user.id,
        data_decisao: new Date().toISOString().slice(0, 10),
      });
      if (negotiationError) throw negotiationError;

      // "negado" mantém a cobrança em aberto (volta pro estado de atrasado);
      // perdão total/desconto parcial encerram a pendência como quitada.
      // Julgamento de negócio — revisitar se o time quiser um status
      // intermediário pra "desconto parcial pago vs. ainda a pagar".
      const novoStatusCharge = form.tipo === "negado" ? "atrasado" : "quitado";

      // Bug conhecido (corrigido aqui): o valor da cobrança nunca era
      // atualizado após a negociação — charge_negotiations guardava o
      // valor combinado só no histórico, mas charges.valor_esperado
      // continuava com o valor cheio pra sempre, inflando relatórios que
      // somam esse campo.
      //
      // "Perdão Total" NÃO grava valor_esperado=0 aqui: a coluna tem
      // `check (valor_esperado > 0)` (Migration 001) — um update pra 0
      // violaria a constraint e falharia. O valor final "0" já fica
      // registrado em charge_negotiations.tipo_resolucao='perdao_total';
      // qualquer relatório que precise do valor de fato devido tem que
      // considerar esse caso via join com charge_negotiations, não
      // assumir que charges.valor_esperado reflete isso sozinho.
      //
      // "Negado" também não muda o valor (a cobrança segue em aberto pelo
      // valor original).
      const updatePayload: { status: string; valor_esperado?: number } = {
        status: novoStatusCharge,
      };
      if (form.tipo === "parcial") {
        updatePayload.valor_esperado = valorNegociado as number;
      }

      const { error: chargeError } = await supabase
        .from("charges")
        .update(updatePayload)
        .eq("id", n.chargeId);
      if (chargeError) throw chargeError;

      return { n, form };
    },
    onSuccess: ({ n, form }) => {
      const msgs: Record<Exclude<Tipo, "">, string> = {
        total: `Olá ${n.inquilino}! Sua pendência de ${n.mes} foi perdoada integralmente. 🎉`,
        parcial: `Olá ${n.inquilino}! Fechamos um acordo em R$ ${form.valorNegociado} referente a ${n.mes}.`,
        negado: `Olá ${n.inquilino}, não foi possível conceder o desconto solicitado. Entre em contato.`,
      };

      // TODO: chamar aqui a função real de envio de mensagem via WhatsApp
      // Ex: await enviarMensagemWhatsApp({ telefone: n.telefone, mensagem });
      // O toast abaixo é só uma simulação visual e deve ser mantido (ou ajustado)
      // para refletir o resultado real do envio (sucesso/erro).
      toast.success("WhatsApp enviado ao inquilino", {
        description: msgs[form.tipo as Exclude<Tipo, "">],
        icon: <MessageCircle className="h-4 w-4" />,
      });

      queryClient.invalidateQueries({ queryKey: COBRANCAS_QUERY_KEY });
    },
    onError: (error: Error) => {
      console.error("Erro ao resolver negociação:", error);
      toast.error(error.message || "Não foi possível registrar a resolução. Tente novamente.");
    },
  });

  // Marcar como pago manualmente: fecha o ciclo fora do fluxo de
  // negociação (Fernanda resolveu por telefone/comprovante direto).
  // status='quitado' já é suficiente pra parar as cobranças automáticas,
  // porque cron_listar_charges_ativas (Migration 008) exclui
  // status='quitado' da varredura diária — nenhuma mudança no cron ou nas
  // RPCs é necessária.
  // data_pagamento e valor_identificado agora vêm do formulário (usuário
  // informa o que realmente aconteceu), em vez de data fixa "hoje" e
  // valor null.
  const marcarPagoMutation = useMutation({
    mutationFn: async ({
      chargeId,
      dataPagamento,
      valorPago,
    }: {
      chargeId: string;
      dataPagamento: string;
      valorPago: number;
    }) => {
      const { error } = await supabase
        .from("charges")
        .update({
          status: "quitado",
          data_pagamento: dataPagamento,
          valor_identificado: valorPago,
        })
        .eq("id", chargeId);
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success("Cobrança marcada como paga", {
        description: "As mensagens automáticas de cobrança para este mês foram interrompidas.",
        icon: <MessageCircle className="h-4 w-4" />,
      });
      queryClient.invalidateQueries({ queryKey: ATRASADAS_QUERY_KEY });
    },
    onError: (error: Error) => {
      console.error("Erro ao marcar cobrança como paga:", error);
      toast.error(error.message || "Não foi possível marcar como paga. Tente novamente.");
    },
  });

  const handleMarcarPago = (n: Atraso) => {
    const form = getPagamentoForm(n);
    const valorPago = Number(form.valorPago);
    if (!form.dataPagamento || !valorPago || valorPago <= 0) {
      toast.error("Informe a data e o valor pago antes de confirmar.");
      return;
    }
    marcarPagoMutation.mutate({
      chargeId: n.chargeId,
      dataPagamento: form.dataPagamento,
      valorPago,
    });
  };

  return (
    <div className="space-y-10">
      <div>
        <PageHeader
          title="Cobranças em Negociação"
          description="Gerencie perdões, descontos parciais e negações."
        />
        <div className="grid gap-4 sm:grid-cols-2 mb-6">
          <StatTile
            tone="c"
            icon={<HandCoins className="h-5 w-5" />}
            label="Em Negociação"
            value={items.length}
            sublabel="cobranças pendentes"
          />
          <StatTile
            tone="b"
            icon={<Wallet className="h-5 w-5" />}
            label="Valor Total"
            value={`R$ ${items.reduce((acc, n) => acc + n.valor, 0).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`}
            sublabel="somado das negociações"
          />
        </div>
        {isError && (
          <p className="text-sm text-destructive mb-4">
            Não foi possível carregar as cobranças em negociação. Verifique sua sessão e tente novamente.
          </p>
        )}
        <div className="grid gap-4">
          {isLoading && (
            <p className="text-sm text-muted-foreground text-center py-8">Carregando...</p>
          )}
          {items.map((n) => {
            const form = getForm(n.chargeId);
            const isPending =
              resolverMutation.isPending && resolverMutation.variables?.chargeId === n.chargeId;
            return (
              <Card key={n.chargeId}>
                <CardHeader className="flex flex-row items-start justify-between space-y-0">
                  <div className="flex items-center gap-3">
                    <Avatar name={n.inquilino} size={36} />
                    <div>
                      <CardTitle className="text-base">{n.inquilino}</CardTitle>
                      <p className="text-sm text-muted-foreground mt-1">{n.imovel}</p>
                    </div>
                  </div>
                  <Badge className="border-[var(--warning-border)] bg-[var(--warning-bg)] text-[var(--warning-fg)] hover:bg-[var(--warning-bg)]">
                    Em Negociação
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-3 gap-4 text-sm">
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">Mês de Referência</div>
                      <div className="font-medium">{n.mes}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">Valor Original</div>
                      <div className="font-semibold text-lg tnum">
                        R$ {n.valor.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">Telefone</div>
                      <div className="font-medium">
                        {n.telefone ?? (
                          <span className="text-muted-foreground italic">Não Registrado</span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="grid md:grid-cols-[1fr,1fr,auto] gap-3 items-end pt-2 border-t">
                    <div className="space-y-1.5">
                      <Label>Tipo de Resolução</Label>
                      <Select
                        value={form.tipo}
                        onValueChange={(v) => updateForm(n.chargeId, { tipo: v as Tipo })}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Selecione..." />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="total">Perdão Total</SelectItem>
                          <SelectItem value="parcial">Desconto Parcial</SelectItem>
                          <SelectItem value="negado">Negado</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    {form.tipo === "parcial" ? (
                      <div className="space-y-1.5">
                        <Label>Valor Negociado (R$)</Label>
                        <Input
                          type="number"
                          placeholder="0,00"
                          value={form.valorNegociado}
                          onChange={(e) => updateForm(n.chargeId, { valorNegociado: e.target.value })}
                        />
                      </div>
                    ) : (
                      <div />
                    )}
                    <Button onClick={() => resolverMutation.mutate(n)} disabled={isPending}>
                      {isPending ? "Confirmando..." : "Confirmar Resolução"}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
          {!isLoading && items.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              Nenhuma cobrança pendente de negociação.
            </p>
          )}
        </div>
      </div>

      <div>
        <PageHeader
          title="Em Atraso (1-14 dias)"
          description="Cobranças ainda dentro do fluxo automático de mensagens."
        />
        {isErrorAtrasadas && (
          <p className="text-sm text-destructive mb-4">
            Não foi possível carregar as cobranças em atraso.
          </p>
        )}
        <div className="grid gap-4">
          {isLoadingAtrasadas && (
            <p className="text-sm text-muted-foreground text-center py-8">Carregando...</p>
          )}
          {atrasadasLeves.map((n) => (
            <AtrasoCard
              key={n.chargeId}
              n={n}
              isPending={
                marcarPagoMutation.isPending &&
                marcarPagoMutation.variables?.chargeId === n.chargeId
              }
              form={getPagamentoForm(n)}
              onChangeForm={(patch) => updatePagamentoForm(n, patch)}
              onMarcarPago={() => handleMarcarPago(n)}
            />
          ))}
          {!isLoadingAtrasadas && atrasadasLeves.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              Nenhuma cobrança em atraso de 1 a 14 dias.
            </p>
          )}
        </div>
      </div>

      <div>
        <PageHeader
          title="Em Atraso Crítico (15+ dias)"
          description="Cobrança já escalonada — resolução manual necessária."
        />
        <div className="grid gap-4">
          {atrasadasCriticas.map((n) => (
            <AtrasoCard
              key={n.chargeId}
              n={n}
              isPending={
                marcarPagoMutation.isPending &&
                marcarPagoMutation.variables?.chargeId === n.chargeId
              }
              form={getPagamentoForm(n)}
              onChangeForm={(patch) => updatePagamentoForm(n, patch)}
              onMarcarPago={() => handleMarcarPago(n)}
            />
          ))}
          {!isLoadingAtrasadas && atrasadasCriticas.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              Nenhuma cobrança em atraso crítico.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}