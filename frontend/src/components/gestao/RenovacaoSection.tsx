import { useState } from "react";
import { toast } from "sonner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, TrendingUp } from "lucide-react";
import { PageHeader } from "./PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Avatar } from "./Avatar";
import { supabase } from "@/lib/supabase";

const RENOVACOES_KEY = ["contract-alerts-renovacao"] as const;

const brl = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;

// Mesmo enum de ContratosSection.tsx (Migration 014) — duplicado aqui de
// propósito, os dois arquivos não compartilham um módulo de tipos comum.
type TipoRenovacao =
  | "novo_contrato"
  | "requer_aditivo"
  | "automatica"
  | "indeterminado_por_lei"
  | "nao_identificado";

// "Acionáveis" = tipos com card interativo (botão de decisão). novo_contrato
// e indeterminado_por_lei nunca ficam pendentes — o primeiro é só
// informativo, o segundo transiciona sozinho por força de lei (cron).
const TIPOS_RENOVACAO_ACIONAVEIS: readonly TipoRenovacao[] = [
  "requer_aditivo",
  "automatica",
  "nao_identificado",
];

const TEXTO_TIPO_RENOVACAO: Record<TipoRenovacao, string> = {
  novo_contrato:
    "A renovação deste contrato será feita com um contrato novo — nenhuma ação necessária aqui.",
  requer_aditivo:
    "Este contrato só prorroga mediante Termo Aditivo. Defina a renovação ou confirme o encerramento.",
  automatica: "Este contrato renova automaticamente — confirme a nova data ou o prazo indefinido.",
  indeterminado_por_lei:
    "Contrato omisso quanto à renovação — por lei, tende a virar prazo indeterminado automaticamente.",
  nao_identificado: "Tipo de renovação não identificado. Defina a renovação ou confirme o encerramento.",
};

/* ============================================================
 * Dados: contract_alerts (renovação, D-60) + estado atual do contrato
 * (status, tipo_renovacao, pendente_decisao_renovacao).
 * ============================================================ */

interface AlertaComContrato {
  alertId: string;
  contractId: string;
  inquilino: string;
  valorAtual: number;
  dataDisparo: string;
  percentualReajuste: number | null;
  valorSugerido: number | null;
  contractStatus: "ativo" | "inativo" | "pendente_confirmacao";
  tipoRenovacao: TipoRenovacao;
}

async function fetchAlertas(tipo: "alerta_renovacao_d60"): Promise<AlertaComContrato[]> {
  // "contracts!inner" (em vez do embed padrão) garante que o join realmente
  // traga os dados do contrato pra cada alerta — sem isso o PostgREST
  // devolveria a linha do alerta com contracts=null quando o relacionamento
  // não bate, o que quebraria a leitura de status/tipo_renovacao abaixo.
  //
  // decisao_gestora='pendente' (Migration 017) é o que faz o card sumir de
  // vez quando a gestora resolve pelo DecisaoRenovacaoDialog ou pelo botão
  // "Confirmar encerramento" abaixo — sem esse filtro, o alerta some do
  // dashboard e volta a aparecer (com o badge de vencido desatualizado),
  // porque a única coisa que mudava antes era o estado em contracts, nunca
  // o próprio alerta.
  const { data, error } = await supabase
    .from("contract_alerts")
    .select(
      "id, contract_id, data_disparo, percentual_reajuste, valor_sugerido, contracts!inner(inquilino_nome, valor_aluguel, status, tipo_renovacao, pendente_decisao_renovacao)",
    )
    .eq("tipo", tipo)
    .eq("decisao_gestora", "pendente")
    .order("data_disparo");
  if (error) throw error;

  return (data ?? [])
    .filter(
      // Mostra o card enquanto o contrato está ativo (dentro da janela
      // D-60) OU enquanto está inativo aguardando decisão de renovação —
      // nos dois casos é o MESMO card, só muda o badge (ver render abaixo).
      // Contratos inativos SEM pendência (ex: tipo_renovacao='novo_contrato'
      // já encerrado normalmente pelo cron) somem daqui, como antes.
      (row: any) => row.contracts?.status === "ativo" || row.contracts?.pendente_decisao_renovacao,
    )
    .map((row: any) => ({
      alertId: row.id,
      contractId: row.contract_id,
      inquilino: row.contracts?.inquilino_nome ?? "—",
      valorAtual: Number(row.contracts?.valor_aluguel ?? 0),
      dataDisparo: row.data_disparo,
      percentualReajuste: row.percentual_reajuste != null ? Number(row.percentual_reajuste) : null,
      valorSugerido: row.valor_sugerido != null ? Number(row.valor_sugerido) : null,
      contractStatus: row.contracts?.status ?? "ativo",
      tipoRenovacao: (row.contracts?.tipo_renovacao ?? "novo_contrato") as TipoRenovacao,
    }));
}

function diasRestantes(dataDisparo: string): number {
  const diff = new Date(dataDisparo).getTime() - Date.now();
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

// Texto e variante de cor do prazo: enquanto está no futuro mostra a
// contagem normal ("Faltam X dias"); quando a data já passou, em vez de
// travar em "Faltam 0 dias" passa a mostrar "Vencido há X dias" para deixar
// claro que o prazo já estourou.
function prazoInfo(dataDisparo: string): { texto: string; vencidoPorData: boolean } {
  const dias = diasRestantes(dataDisparo);
  if (dias > 0) return { texto: `Faltam ${dias} ${dias === 1 ? "dia" : "dias"}`, vencidoPorData: false };
  if (dias === 0) return { texto: "Vence hoje", vencidoPorData: false };
  const atraso = Math.abs(dias);
  return { texto: `Vencido há ${atraso} ${atraso === 1 ? "dia" : "dias"}`, vencidoPorData: true };
}

/* ============================================================
 * Diálogo de decisão: nova data de vencimento OU prazo indefinido.
 * Escreve DIRETO na tabela contracts, mesmo padrão já usado pelos botões
 * "Desativar/Reativar Contrato" em ContratosSection.tsx (RLS
 * staff_full_access) — não existe RPC pra essa ação, é a própria sessão da
 * gestora fazendo o update. Funciona tanto pro card ainda ativo (D-60,
 * decidindo antes do vencimento) quanto pro card já vencido/inativo
 * (reativando o contrato) — é a mesma decisão nos dois casos.
 *
 * Depois de decidir em contracts, também grava decisao_gestora='renovado'
 * no próprio alerta (Migration 017) — é isso que faz o card sumir da
 * lista em fetchAlertas acima. Sem esse segundo update, o alerta ficava
 * 'pendente' pra sempre e o card reaparecia (com badge de vencido) mesmo
 * já resolvido.
 * ============================================================ */

function DecisaoRenovacaoDialog({
  contractId,
  alertId,
  onConfirmado,
}: {
  contractId: string;
  alertId: string;
  onConfirmado: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [modo, setModo] = useState<"nova_data" | "indefinido">("nova_data");
  const [novaData, setNovaData] = useState("");

  const mutation = useMutation({
    mutationFn: async () => {
      const { error: errContrato } = await supabase
        .from("contracts")
        .update({
          status: "ativo",
          pendente_decisao_renovacao: false,
          ...(modo === "indefinido"
            ? { prazo_indeterminado: true }
            : { data_termino: novaData, prazo_indeterminado: false }),
        })
        .eq("id", contractId);
      if (errContrato) throw errContrato;

      const { error: errAlerta } = await supabase
        .from("contract_alerts")
        .update({ decisao_gestora: "renovado" })
        .eq("id", alertId);
      if (errAlerta) throw errAlerta;
    },
    onSuccess: () => {
      toast.success("Renovação definida com sucesso");
      setOpen(false);
      setNovaData("");
      onConfirmado();
    },
    onError: (error: any) => {
      console.error("Erro ao definir renovação:", error);
      if (error?.code === "23505") {
        toast.error(
          "Já existe outro contrato ativo com este telefone. Verifique se este inquilino não migrou para um contrato novo antes de reativar este.",
        );
      } else {
        toast.error("Não foi possível definir a renovação. Tente novamente.");
      }
    },
  });

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        Definir renovação
      </Button>
      <AlertDialog open={open} onOpenChange={(o) => !mutation.isPending && setOpen(o)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Renovação do contrato</AlertDialogTitle>
            <AlertDialogDescription>
              Defina uma nova data de vencimento ou marque o contrato como prazo indefinido.
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label className="text-sm">Renovação</Label>
              <Select value={modo} onValueChange={(v) => setModo(v as typeof modo)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="nova_data">Nova data de vencimento</SelectItem>
                  <SelectItem value="indefinido">Prazo indefinido</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {modo === "nova_data" && (
              <div className="space-y-1.5">
                <Label className="text-sm">Nova data de vencimento</Label>
                <Input type="date" value={novaData} onChange={(e) => setNovaData(e.target.value)} />
              </div>
            )}
          </div>

          <AlertDialogFooter>
            <AlertDialogCancel disabled={mutation.isPending}>Cancelar</AlertDialogCancel>
            <Button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending || (modo === "nova_data" && !novaData)}
            >
              {mutation.isPending ? "Confirmando..." : "Confirmar"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

/* ============================================================
 * Seção: Renovação — contract_alerts tipo='alerta_renovacao_d60'.
 *
 * Um único feed de cards. O comportamento de cada card depende de
 * tipoRenovacao (Migration 014):
 *   - novo_contrato / indeterminado_por_lei: informativo, sem ação.
 *   - requer_aditivo / automatica / nao_identificado: interativo — botão
 *     de decisão sempre visível, e "Confirmar encerramento" quando o
 *     contrato já foi desativado pelo cron por falta de decisão (badge
 *     vermelho). O card não muda de seção quando isso acontece — continua
 *     no mesmo lugar da lista, só muda de aparência.
 * ============================================================ */

function RenovacaoSectionInner() {
  const queryClient = useQueryClient();
  const { data: items = [], isLoading } = useQuery({
    queryKey: RENOVACOES_KEY,
    queryFn: () => fetchAlertas("alerta_renovacao_d60"),
  });

  const invalidar = () => queryClient.invalidateQueries({ queryKey: RENOVACOES_KEY });

  const descartarMutation = useMutation({
    mutationFn: async ({ contractId, alertId }: { contractId: string; alertId: string }) => {
      const { error: errContrato } = await supabase
        .from("contracts")
        .update({ pendente_decisao_renovacao: false })
        .eq("id", contractId);
      if (errContrato) throw errContrato;

      // Mesma lógica do DecisaoRenovacaoDialog acima: sem gravar a decisão
      // no próprio alerta (Migration 017), o card reaparecia depois de
      // "resolvido" porque contract_alerts.decisao_gestora continuava
      // 'pendente' pra sempre.
      const { error: errAlerta } = await supabase
        .from("contract_alerts")
        .update({ decisao_gestora: "encerrado" })
        .eq("id", alertId);
      if (errAlerta) throw errAlerta;
    },
    onSuccess: () => {
      toast.success("Encerramento confirmado");
      invalidar();
    },
    onError: (error) => {
      console.error("Erro ao confirmar encerramento:", error);
      toast.error("Não foi possível confirmar o encerramento. Tente novamente.");
    },
  });

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <CalendarClock className="h-4 w-4 text-primary" />
        <h2 className="text-lg font-semibold">Renovação</h2>
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        Contratos em janela de alerta (D-60 antes do término) e contratos vencidos aguardando
        decisão de renovação, com o valor sugerido para o próximo ciclo.
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
            const { texto: textoPrazo, vencidoPorData } = prazoInfo(a.dataDisparo);
            // status='inativo' é o sinal mais confiável de que o contrato
            // venceu sem decisão (o cron só marca isso na data_termino
            // real) — a data matemática (vencidoPorData) é só um reforço
            // pro dia exato em que o card ainda está 'ativo' mas a
            // contagem já zerou.
            const contratoInativo = a.contractStatus === "inativo";
            const vencido = contratoInativo || vencidoPorData;
            const acionavel = TIPOS_RENOVACAO_ACIONAVEIS.includes(a.tipoRenovacao);

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
                  <Badge
                    className={
                      vencido
                        ? "border-red-200 bg-red-50 text-red-700 hover:bg-red-50 dark:border-red-900 dark:bg-red-950 dark:text-red-400"
                        : "border-[var(--info-border)] bg-[var(--info-bg)] text-[var(--info-fg)] hover:bg-[var(--info-bg)]"
                    }
                  >
                    D-60 Renovação · {textoPrazo}
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-4">
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

                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm text-muted-foreground">
                      {TEXTO_TIPO_RENOVACAO[a.tipoRenovacao]}
                    </p>
                    {acionavel && (
                      <div className="flex gap-2 shrink-0">
                        {contratoInativo && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => descartarMutation.mutate({ contractId: a.contractId, alertId: a.alertId })}
                            disabled={descartarMutation.isPending}
                          >
                            Confirmar encerramento
                          </Button>
                        )}
                        <DecisaoRenovacaoDialog
                          contractId={a.contractId}
                          alertId={a.alertId}
                          onConfirmado={invalidar}
                        />
                      </div>
                    )}
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

export function RenovacaoSection() {
  return (
    <div className="space-y-10">
      <PageHeader
        title="Renovação"
        description="Contratos em janela de alerta (D-60 antes do término) com o valor sugerido para o novo contrato."
      />

      <RenovacaoSectionInner />
    </div>
  );
}