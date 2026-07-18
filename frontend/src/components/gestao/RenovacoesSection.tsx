import { useState } from "react";
import { toast } from "sonner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, TrendingUp, Sparkles, Wrench, Gift } from "lucide-react";
import { PageHeader } from "./PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Separator } from "@/components/ui/separator";
import { Avatar } from "./Avatar";
import { supabase } from "@/lib/supabase";

const CONTRATOS_ATIVOS_KEY = ["contratos-ativos-reajuste"] as const;
const REAJUSTES_ANIVERSARIO_KEY = ["contract-alerts-reajuste"] as const;
const RENOVACOES_KEY = ["contract-alerts-renovacao"] as const;

type Decisao = "" | "sugerido" | "manual" | "encerrar";

const brl = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;

/* ============================================================
 * Dados: contratos ativos (pra reajuste manual, sem vínculo com alerta)
 * ============================================================ */

interface ContratoAtivo {
  id: string;
  inquilino: string;
  imovel: string;
  valorAtual: number;
}

async function fetchContratosAtivos(): Promise<ContratoAtivo[]> {
  const { data, error } = await supabase
    .from("contracts")
    .select("id, inquilino_nome, imovel_endereco, valor_aluguel")
    .eq("status", "ativo")
    .order("inquilino_nome");
  if (error) throw error;
  return (data ?? []).map((c) => ({
    id: c.id,
    inquilino: c.inquilino_nome,
    imovel: c.imovel_endereco,
    valorAtual: Number(c.valor_aluguel),
  }));
}

/* ============================================================
 * Dados: contract_alerts (reajuste de aniversário e renovação)
 * ============================================================ */

interface AlertaComContrato {
  alertId: string;
  contractId: string;
  inquilino: string;
  valorAtual: number;
  dataDisparo: string;
  percentualReajuste: number | null;
  valorSugerido: number | null;
}

async function fetchAlertas(tipo: "calculo_reajuste_d30" | "alerta_renovacao_d60"): Promise<AlertaComContrato[]> {
  // "contracts!inner" (em vez do embed padrão) é necessário pra poder filtrar
  // por contracts.status abaixo — sem o !inner, o filtro no relacionamento é
  // ignorado pelo PostgREST e alertas de contratos já inativos continuam
  // aparecendo na lista (era exatamente o bug: contrato desativado ainda
  // mostrava reajuste/renovação pendente).
  const { data, error } = await supabase
    .from("contract_alerts")
    .select(
      "id, contract_id, data_disparo, percentual_reajuste, valor_sugerido, decisao_gestora, contracts!inner(inquilino_nome, valor_aluguel, status)",
    )
    .eq("tipo", tipo)
    .or("decisao_gestora.is.null,decisao_gestora.eq.pendente")
    .eq("contracts.status", "ativo")
    .order("data_disparo");
  if (error) throw error;

  return (data ?? []).map((row: any) => ({
    alertId: row.id,
    contractId: row.contract_id,
    inquilino: row.contracts?.inquilino_nome ?? "—",
    valorAtual: Number(row.contracts?.valor_aluguel ?? 0),
    dataDisparo: row.data_disparo,
    percentualReajuste: row.percentual_reajuste != null ? Number(row.percentual_reajuste) : null,
    valorSugerido: row.valor_sugerido != null ? Number(row.valor_sugerido) : null,
  }));
}

function diasRestantes(dataDisparo: string): number {
  const diff = new Date(dataDisparo).getTime() - Date.now();
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)));
}

/* ============================================================
 * Seção 1: Reajustes manuais — edita contracts.valor_aluguel direto,
 * sem depender de nenhum alerta ter sido disparado.
 * ============================================================ */

function ReajustesManuaisSection() {
  const queryClient = useQueryClient();
  const { data: contratos = [], isLoading } = useQuery({
    queryKey: CONTRATOS_ATIVOS_KEY,
    queryFn: fetchContratosAtivos,
  });
  const [inputs, setInputs] = useState<Record<string, string>>({});

  const aplicarMutation = useMutation({
    mutationFn: async (c: ContratoAtivo) => {
      const raw = (inputs[c.id] ?? "").replace(",", ".");
      const novo = parseFloat(raw);
      if (!Number.isFinite(novo) || novo <= 0) throw new Error("Informe um valor válido");

      const { error } = await supabase
        .from("contracts")
        .update({ valor_aluguel: novo })
        .eq("id", c.id);
      if (error) throw error;
      return novo;
    },
    onSuccess: (novo, c) => {
      setInputs((prev) => ({ ...prev, [c.id]: "" }));
      toast.success("Reajuste manual aplicado", {
        description: `${c.inquilino}: ${brl(c.valorAtual)} → ${brl(novo)}`,
      });
      queryClient.invalidateQueries({ queryKey: CONTRATOS_ATIVOS_KEY });
    },
    onError: (error: Error) => toast.error(error.message || "Não foi possível aplicar o reajuste"),
  });

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <Wrench className="h-4 w-4 text-primary" />
        <h2 className="text-lg font-semibold">Reajustes manuais</h2>
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        Um card para cada contrato ativo. Atualize o valor a qualquer momento — a lista
        reflete automaticamente contratos adicionados ou removidos.
      </p>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Carregando...</p>
      ) : contratos.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Nenhum contrato ativo no momento.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {contratos.map((c) => (
            <Card key={c.id}>
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <Avatar name={c.inquilino} size={34} />
                    <div>
                      <CardTitle className="text-base">{c.inquilino}</CardTitle>
                      <p className="text-xs text-muted-foreground mt-0.5">{c.imovel}</p>
                    </div>
                  </div>
                  <Badge variant="secondary">Ativo</Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="rounded-lg bg-muted/30 p-3">
                  <div className="text-xs uppercase text-muted-foreground">Valor atual</div>
                  <div className="font-semibold tnum">{brl(c.valorAtual)}</div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`man-${c.id}`}>Novo valor (R$)</Label>
                  <div className="flex gap-2">
                    <Input
                      id={`man-${c.id}`}
                      type="number"
                      placeholder="0,00"
                      value={inputs[c.id] ?? ""}
                      onChange={(e) => setInputs((prev) => ({ ...prev, [c.id]: e.target.value }))}
                    />
                    <Button
                      onClick={() => aplicarMutation.mutate(c)}
                      disabled={aplicarMutation.isPending && aplicarMutation.variables?.id === c.id}
                    >
                      Aplicar
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}

/* ============================================================
 * Seção 2: Reajustes de aniversário — contract_alerts
 * tipo='calculo_reajuste_d30', pendentes de decisão.
 * ============================================================ */

function ReajustesAniversarioSection() {
  const queryClient = useQueryClient();
  const { data: items = [], isLoading } = useQuery({
    queryKey: REAJUSTES_ANIVERSARIO_KEY,
    queryFn: () => fetchAlertas("calculo_reajuste_d30"),
  });
  const [modos, setModos] = useState<Record<string, "sugerido" | "manual">>({});
  const [manuais, setManuais] = useState<Record<string, string>>({});

  const aplicarMutation = useMutation({
    mutationFn: async (a: AlertaComContrato) => {
      const modo = modos[a.alertId] ?? "sugerido";
      const sugerido =
        a.valorSugerido ?? a.valorAtual * (1 + (a.percentualReajuste ?? 0) / 100);
      const novo =
        modo === "sugerido" ? sugerido : parseFloat((manuais[a.alertId] ?? "").replace(",", "."));

      if (!Number.isFinite(novo) || novo <= 0) throw new Error("Informe um valor válido");

      const { error: alertError } = await supabase
        .from("contract_alerts")
        .update({
          decisao_gestora: modo === "sugerido" ? "renovar_sugerido" : "renovar_ajustado",
          valor_aplicado: novo,
        })
        .eq("id", a.alertId);
      if (alertError) throw alertError;

      const { error: contractError } = await supabase
        .from("contracts")
        .update({ valor_aluguel: novo })
        .eq("id", a.contractId);
      if (contractError) throw contractError;

      return novo;
    },
    onSuccess: (novo, a) => {
      toast.success("Reajuste de aniversário aplicado", {
        description: `${a.inquilino}: ${brl(a.valorAtual)} → ${brl(novo)}`,
      });
      queryClient.invalidateQueries({ queryKey: REAJUSTES_ANIVERSARIO_KEY });
      queryClient.invalidateQueries({ queryKey: CONTRATOS_ATIVOS_KEY });
    },
    onError: (error: Error) => toast.error(error.message || "Não foi possível aplicar o reajuste"),
  });

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <Gift className="h-4 w-4 text-primary" />
        <h2 className="text-lg font-semibold">Reajustes de aniversário</h2>
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        Cards gerados automaticamente quando o agente envia a mensagem no WhatsApp a
        30 dias do aniversário do contrato. Após aplicada, a mudança some desta lista.
      </p>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Carregando...</p>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Nenhum reajuste de aniversário pendente.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {items.map((a) => {
            const sugerido =
              a.valorSugerido ?? a.valorAtual * (1 + (a.percentualReajuste ?? 0) / 100);
            const modo = modos[a.alertId] ?? "sugerido";
            const manualNum = parseFloat((manuais[a.alertId] ?? "").replace(",", "."));
            const dias = diasRestantes(a.dataDisparo);
            const isPending =
              aplicarMutation.isPending && aplicarMutation.variables?.alertId === a.alertId;
            return (
              <Card key={a.alertId}>
                <CardHeader className="flex flex-row items-start justify-between space-y-0">
                  <div className="flex items-center gap-3">
                    <Avatar name={a.inquilino} size={40} />
                    <div>
                      <CardTitle className="text-base flex items-center gap-1.5">
                        {a.inquilino}
                        <Sparkles className="h-3.5 w-3.5 text-[var(--brand-strong)]" />
                      </CardTitle>
                      <p className="text-xs text-muted-foreground">
                        Aniversário: {new Date(a.dataDisparo).toLocaleDateString("pt-BR")}
                      </p>
                    </div>
                  </div>
                  <Badge className="border-[var(--warning-border)] bg-[var(--warning-bg)] text-[var(--warning-fg)] hover:bg-[var(--warning-bg)]">
                    Faltam {dias} {dias === 1 ? "dia" : "dias"}
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm bg-muted/30 rounded-lg p-4">
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">Valor atual</div>
                      <div className="font-semibold tnum">{brl(a.valorAtual)}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">Taxa do contrato</div>
                      <div className="font-semibold flex items-center gap-1 tnum text-[var(--success-accent)]">
                        <TrendingUp className="h-3.5 w-3.5" />
                        {(a.percentualReajuste ?? 0).toFixed(2)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">Valor sugerido</div>
                      <div className="font-semibold text-primary tnum">{brl(sugerido)}</div>
                    </div>
                  </div>

                  <RadioGroup
                    value={modo}
                    onValueChange={(v) =>
                      setModos((prev) => ({ ...prev, [a.alertId]: v as "sugerido" | "manual" }))
                    }
                    className="grid gap-2"
                  >
                    <label className="flex items-center gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40">
                      <RadioGroupItem value="sugerido" id={`${a.alertId}-s`} />
                      <span className="text-sm">Aceitar valor sugerido ({brl(sugerido)})</span>
                    </label>
                    <label className="flex items-center gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40">
                      <RadioGroupItem value="manual" id={`${a.alertId}-m`} />
                      <span className="text-sm">Alterar manualmente</span>
                    </label>
                  </RadioGroup>

                  {modo === "manual" && (
                    <div className="space-y-1.5">
                      <Label>Novo valor (R$)</Label>
                      <Input
                        type="number"
                        placeholder="0,00"
                        value={manuais[a.alertId] ?? ""}
                        onChange={(e) =>
                          setManuais((prev) => ({ ...prev, [a.alertId]: e.target.value }))
                        }
                        className="max-w-xs"
                      />
                    </div>
                  )}

                  <div className="flex justify-end">
                    <Button
                      onClick={() => aplicarMutation.mutate(a)}
                      disabled={
                        isPending || (modo === "manual" && (!Number.isFinite(manualNum) || manualNum <= 0))
                      }
                    >
                      Aplicar reajuste
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </section>
  );
}

/* ============================================================
 * Seção 3: Renovação — contract_alerts tipo='alerta_renovacao_d60',
 * pendentes de decisão.
 * ============================================================ */

function RenovacaoSection() {
  const queryClient = useQueryClient();
  const { data: items = [], isLoading } = useQuery({
    queryKey: RENOVACOES_KEY,
    queryFn: () => fetchAlertas("alerta_renovacao_d60"),
  });
  const [decisoes, setDecisoes] = useState<Record<string, Decisao>>({});
  const [manuais, setManuais] = useState<Record<string, string>>({});

  const confirmarMutation = useMutation({
    mutationFn: async (a: AlertaComContrato) => {
      const decisao = decisoes[a.alertId] ?? "";
      if (!decisao) throw new Error("Selecione uma decisão");

      if (decisao === "encerrar") {
        const { error: alertError } = await supabase
          .from("contract_alerts")
          .update({ decisao_gestora: "encerrar" })
          .eq("id", a.alertId);
        if (alertError) throw alertError;

        const { error: contractError } = await supabase
          .from("contracts")
          .update({ status: "inativo" })
          .eq("id", a.contractId);
        if (contractError) throw contractError;

        return { novo: null as number | null, decisao };
      }

      const sugerido = a.valorSugerido ?? a.valorAtual * (1 + (a.percentualReajuste ?? 0) / 100);
      const novo =
        decisao === "sugerido" ? sugerido : parseFloat((manuais[a.alertId] ?? "").replace(",", "."));

      if (decisao === "manual" && (!Number.isFinite(novo) || novo <= 0)) {
        throw new Error("Informe um valor manual válido");
      }

      const { error: alertError } = await supabase
        .from("contract_alerts")
        .update({
          decisao_gestora: decisao === "sugerido" ? "renovar_sugerido" : "renovar_ajustado",
          valor_aplicado: novo,
        })
        .eq("id", a.alertId);
      if (alertError) throw alertError;

      const { error: contractError } = await supabase
        .from("contracts")
        .update({ valor_aluguel: novo })
        .eq("id", a.contractId);
      if (contractError) throw contractError;

      return { novo, decisao };
    },
    onSuccess: ({ novo, decisao }, a) => {
      if (decisao === "encerrar") {
        toast.success("Contrato encerrado", {
          description: `Fluxo de desativação iniciado para ${a.inquilino}.`,
        });
      } else {
        toast.success("Renovação confirmada", {
          description: `Valor atualizado para ${brl(novo!)} no próximo ciclo.`,
        });
      }
      queryClient.invalidateQueries({ queryKey: RENOVACOES_KEY });
      queryClient.invalidateQueries({ queryKey: CONTRATOS_ATIVOS_KEY });
    },
    onError: (error: Error) => toast.error(error.message || "Não foi possível confirmar a decisão"),
  });

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <CalendarClock className="h-4 w-4 text-primary" />
        <h2 className="text-lg font-semibold">Renovação</h2>
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        Contratos em janela de alerta (D-60 antes do término). Registre a decisão
        administrativa — o valor é atualizado no contrato existente.
      </p>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Carregando...</p>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Nenhum contrato em janela de renovação no momento.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {items.map((a) => {
            const sugerido = a.valorSugerido ?? a.valorAtual * (1 + (a.percentualReajuste ?? 0) / 100);
            const decisao = decisoes[a.alertId] ?? "";
            const isPending =
              confirmarMutation.isPending && confirmarMutation.variables?.alertId === a.alertId;

            return (
              <Card key={a.alertId}>
                <CardHeader className="flex flex-row items-start justify-between space-y-0">
                  <div className="flex items-center gap-3">
                    <Avatar name={a.inquilino} size={40} />
                    <div>
                      <CardTitle className="text-base flex items-center gap-1.5">
                        {a.inquilino}
                        <CalendarClock className="h-3.5 w-3.5 text-[var(--info-strong)]" />
                      </CardTitle>
                      <p className="text-xs text-muted-foreground">
                        Término: {new Date(a.dataDisparo).toLocaleDateString("pt-BR")}
                      </p>
                    </div>
                  </div>
                  <Badge className="border-[var(--info-border)] bg-[var(--info-bg)] text-[var(--info-fg)] hover:bg-[var(--info-bg)]">D-60 Renovação</Badge>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm bg-muted/30 rounded-lg p-4">
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">Valor Atual</div>
                      <div className="font-semibold tnum">{brl(a.valorAtual)}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">Reajuste</div>
                      <div className="font-semibold flex items-center gap-1 tnum text-[var(--success-accent)]">
                        <TrendingUp className="h-3.5 w-3.5" />
                        {(a.percentualReajuste ?? 0).toFixed(2)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">Valor Sugerido</div>
                      <div className="font-semibold text-primary tnum">{brl(sugerido)}</div>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <Label>Decisão</Label>
                    <RadioGroup
                      value={decisao}
                      onValueChange={(v) =>
                        setDecisoes((prev) => ({ ...prev, [a.alertId]: v as Decisao }))
                      }
                      className="grid gap-2"
                    >
                      <label className="flex items-center gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40">
                        <RadioGroupItem value="sugerido" id={`${a.alertId}-s`} />
                        <span className="text-sm">Renovar com valor sugerido ({brl(sugerido)})</span>
                      </label>
                      <label className="flex items-center gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40">
                        <RadioGroupItem value="manual" id={`${a.alertId}-m`} />
                        <span className="text-sm">Renovar com valor ajustado manualmente</span>
                      </label>
                      <label className="flex items-center gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40">
                        <RadioGroupItem value="encerrar" id={`${a.alertId}-e`} />
                        <span className="text-sm">Encerrar contrato</span>
                      </label>
                    </RadioGroup>

                    {decisao === "manual" && (
                      <div className="space-y-1.5">
                        <Label>Novo valor (R$)</Label>
                        <Input
                          type="number"
                          placeholder="0,00"
                          value={manuais[a.alertId] ?? ""}
                          onChange={(e) =>
                            setManuais((prev) => ({ ...prev, [a.alertId]: e.target.value }))
                          }
                          className="max-w-xs"
                        />
                      </div>
                    )}

                    <div className="flex justify-end">
                      <Button
                        onClick={() => confirmarMutation.mutate(a)}
                        disabled={isPending}
                        variant={decisao === "encerrar" ? "destructive" : "default"}
                      >
                        {decisao === "encerrar" ? "Confirmar Encerramento" : "Confirmar Renovação"}
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </section>
  );
}

/* ============================================================
 * Componente exportado
 * ============================================================ */

export function RenovacoesSection() {
  return (
    <div className="space-y-10">
      <PageHeader
        title="Renovações e Reajustes"
        description="Reajustes manuais a qualquer momento, reajustes automáticos de aniversário e renovações em janela de alerta — tudo em um único painel."
      />

      <ReajustesManuaisSection />
      <Separator />
      <ReajustesAniversarioSection />
      <Separator />
      <RenovacaoSection />
    </div>
  );
}
