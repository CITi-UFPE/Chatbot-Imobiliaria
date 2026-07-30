import { useQuery } from "@tanstack/react-query";
import { CalendarClock, TrendingUp, Info } from "lucide-react";
import { PageHeader } from "./PageHeader";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Avatar } from "./Avatar";
import { supabase } from "@/lib/supabase";

const RENOVACOES_KEY = ["contract-alerts-renovacao"] as const;

const brl = (v: number) => `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;

/* ============================================================
 * Dados: contract_alerts (renovação)
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

async function fetchAlertas(tipo: "alerta_renovacao_d60"): Promise<AlertaComContrato[]> {
  // "contracts!inner" (em vez do embed padrão) é necessário pra poder filtrar
  // por contracts.status abaixo — sem o !inner, o filtro no relacionamento é
  // ignorado pelo PostgREST e alertas de contratos já inativos continuam
  // aparecendo na lista. Este filtro é o único motivo do aviso sumir: quando
  // o cron do A4 desativa o contrato na data_termino (status='inativo'),
  // esta query naturalmente para de trazer o alerta — sem nenhuma escrita
  // vinda desta tela.
  const { data, error } = await supabase
    .from("contract_alerts")
    .select(
      "id, contract_id, data_disparo, percentual_reajuste, valor_sugerido, contracts!inner(inquilino_nome, valor_aluguel, status)",
    )
    .eq("tipo", tipo)
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
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

// Texto e variante de cor do prazo: enquanto está no futuro mostra a
// contagem normal ("Faltam X dias"); quando a data já passou, em vez de
// travar em "Faltam 0 dias" passa a mostrar "Vencido há X dias" para deixar
// claro que o prazo já estourou.
function prazoInfo(dataDisparo: string): { texto: string; vencido: boolean } {
  const dias = diasRestantes(dataDisparo);
  if (dias > 0) return { texto: `Faltam ${dias} ${dias === 1 ? "dia" : "dias"}`, vencido: false };
  if (dias === 0) return { texto: "Vence hoje", vencido: false };
  const atraso = Math.abs(dias);
  return { texto: `Vencido há ${atraso} ${atraso === 1 ? "dia" : "dias"}`, vencido: true };
}

/* ============================================================
 * Seção: Renovação — contract_alerts tipo='alerta_renovacao_d60'.
 *
 * Puramente informativo, sem nenhuma ação da gestora. O contrato novo (se
 * houver) é criado em outro lugar do sistema (fluxo de leitura por IA); o
 * contrato atual é desativado automaticamente pelo cron do A4 quando chega
 * em data_termino, e o aviso desaparece sozinho neste momento.
 * ============================================================ */

function RenovacaoSectionInner() {
  const { data: items = [], isLoading } = useQuery({
    queryKey: RENOVACOES_KEY,
    queryFn: () => fetchAlertas("alerta_renovacao_d60"),
  });

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <CalendarClock className="h-4 w-4 text-primary" />
        <h2 className="text-lg font-semibold">Renovação</h2>
      </div>
      <p className="text-sm text-muted-foreground mb-1">
        Contratos em janela de alerta (D-60 antes do término), com o valor sugerido
        para o próximo ciclo.
      </p>
      <div className="flex items-start gap-2 text-sm text-muted-foreground bg-muted/30 rounded-lg p-3 mb-4">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <p>
          Painel só de aviso, sem nenhuma ação aqui. O contrato é desativado
          automaticamente na data de término e o aviso some sozinho.
        </p>
      </div>

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
            const { texto: textoPrazo, vencido } = prazoInfo(a.dataDisparo);

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
                <CardContent>
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