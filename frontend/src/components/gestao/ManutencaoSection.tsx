import { useState } from "react";
import { toast } from "sonner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Zap, Droplet, Hammer, Paintbrush, Wrench, CheckCircle2, Save, Loader2, ClipboardList, AlertCircle, History, ListFilter } from "lucide-react";
import { PageHeader } from "./PageHeader";
import { StatTile } from "./StatTile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { supabase } from "@/lib/supabase";
import type { MaintenanceCategoria, MaintenanceStatus } from "@/lib/database.types";

const MANUTENCAO_QUERY_KEY = ["maintenance-tickets"] as const;
const MANUTENCAO_STATS_QUERY_KEY = ["maintenance-tickets-stats"] as const;

// Teto do histórico completo: pensando em escala, não faz sentido puxar
// todo ticket resolvido desde o início dos tempos de uma vez só. 100 dá
// bastante margem pro uso atual sem virar paginação de verdade — se o
// volume crescer a ponto de isso ficar curto, aí sim vale investir numa
// paginação real.
const LIMITE_HISTORICO = 100;

interface Ticket {
  id: string;
  categoria: MaintenanceCategoria;
  descricao: string;
  imovel: string;
  abertura: string; // já formatada pt-BR
  observacao: string;
  status: MaintenanceStatus;
}

interface TicketStats {
  total: number;
  abertos: number;
  resolvidos: number;
}

async function fetchTicketStats(): Promise<TicketStats> {
  const [totalRes, resolvidosRes] = await Promise.all([
    supabase.from("maintenance_tickets").select("id", { count: "exact", head: true }),
    supabase
      .from("maintenance_tickets")
      .select("id", { count: "exact", head: true })
      .eq("status", "resolvido"),
  ]);
  if (totalRes.error) throw totalRes.error;
  if (resolvidosRes.error) throw resolvidosRes.error;

  const total = totalRes.count ?? 0;
  const resolvidos = resolvidosRes.count ?? 0;
  return { total, resolvidos, abertos: total - resolvidos };
}

// incluirResolvidos=false (padrão) mostra só o que ainda precisa de ação
// (aberto/em_andamento). true traz o histórico completo, com um limite —
// ver LIMITE_HISTORICO.
async function fetchTickets(incluirResolvidos: boolean): Promise<Ticket[]> {
  let query = supabase
    .from("maintenance_tickets")
    .select("id, categoria, descricao, observacao, status, data_abertura, contracts(imovel_endereco)")
    .order("data_abertura", { ascending: false });

  if (incluirResolvidos) {
    query = query.limit(LIMITE_HISTORICO);
  } else {
    query = query.in("status", ["aberto", "em_andamento"]);
  }

  const { data, error } = await query;
  if (error) throw error;

  return (data ?? []).map((row: any) => ({
    id: row.id,
    categoria: row.categoria,
    descricao: row.descricao,
    imovel: row.contracts?.imovel_endereco ?? "—",
    abertura: new Date(row.data_abertura).toLocaleDateString("pt-BR"),
    observacao: row.observacao ?? "",
    status: row.status,
  }));
}

const iconMap: Record<MaintenanceCategoria, React.ComponentType<{ className?: string }>> = {
  eletrica: Zap,
  hidraulica: Droplet,
  estrutural: Hammer,
  pintura: Paintbrush,
  outros: Wrench,
};

const labelMap: Record<MaintenanceCategoria, string> = {
  eletrica: "Elétrica",
  hidraulica: "Hidráulica",
  estrutural: "Estrutural",
  pintura: "Pintura",
  outros: "Outros",
};

const colorMap: Record<MaintenanceCategoria, string> = {
  eletrica: "cat-eletrica",
  hidraulica: "cat-hidraulica",
  estrutural: "cat-estrutural",
  pintura: "cat-pintura",
  outros: "cat-outros",
};

export function ManutencaoSection() {
  const queryClient = useQueryClient();
  const [observacoes, setObservacoes] = useState<Record<string, string>>({});
  const [mostrarHistorico, setMostrarHistorico] = useState(false);

  const { data: stats } = useQuery({
    queryKey: MANUTENCAO_STATS_QUERY_KEY,
    queryFn: fetchTicketStats,
  });

  const { data: tickets = [], isLoading, isError } = useQuery({
    queryKey: [...MANUTENCAO_QUERY_KEY, mostrarHistorico],
    queryFn: () => fetchTickets(mostrarHistorico),
  });

  const salvarObservacaoMutation = useMutation({
    mutationFn: async (t: Ticket) => {
      const observacao = observacoes[t.id] ?? t.observacao;
      const { error } = await supabase
        .from("maintenance_tickets")
        .update({ observacao })
        .eq("id", t.id);
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success("Observação salva");
      queryClient.invalidateQueries({ queryKey: MANUTENCAO_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: MANUTENCAO_STATS_QUERY_KEY });
    },
    onError: (error: Error) => {
      console.error("Erro ao salvar observação:", error);
      toast.error(error.message || "Não foi possível salvar a observação. Tente novamente.");
    },
  });

  const resolverMutation = useMutation({
    mutationFn: async (t: Ticket) => {
      const observacao = observacoes[t.id] ?? t.observacao;
      const { error } = await supabase
        .from("maintenance_tickets")
        .update({
          status: "resolvido",
          observacao,
          data_resolucao: new Date().toISOString(),
        })
        .eq("id", t.id);
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success("Ticket arquivado como resolvido", {
        icon: <CheckCircle2 className="h-4 w-4" />,
      });
      queryClient.invalidateQueries({ queryKey: MANUTENCAO_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: MANUTENCAO_STATS_QUERY_KEY });
    },
    onError: (error: Error) => {
      console.error("Erro ao resolver ticket:", error);
      toast.error(error.message || "Não foi possível resolver o ticket. Tente novamente.");
    },
  });

  return (
    <div>
      <PageHeader
        title="Manutenção"
        description="Tickets abertos automaticamente pelo sistema A3. Registre observações do prestador e feche quando concluído."
      />

      <div className="grid gap-4 sm:grid-cols-3 mb-6">
        <StatTile
          tone="a"
          icon={<ClipboardList className="h-5 w-5" />}
          label="Total de Tickets"
          value={stats?.total ?? 0}
          sublabel="no total"
        />
        <StatTile
          tone="c"
          icon={<AlertCircle className="h-5 w-5" />}
          label="Abertos"
          value={stats?.abertos ?? 0}
          sublabel="aguardando resolução"
        />
        <StatTile
          tone="d"
          icon={<CheckCircle2 className="h-5 w-5" />}
          label="Resolvidos"
          value={stats?.resolvidos ?? 0}
          sublabel="concluídos"
        />
      </div>

      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-muted-foreground">
          {mostrarHistorico
            ? `Mostrando histórico completo (últimos ${LIMITE_HISTORICO} tickets).`
            : "Mostrando apenas tickets em aberto."}
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setMostrarHistorico((prev) => !prev)}
        >
          {mostrarHistorico ? (
            <>
              <ListFilter className="h-4 w-4 mr-2" /> Ver só em aberto
            </>
          ) : (
            <>
              <History className="h-4 w-4 mr-2" /> Ver histórico completo
            </>
          )}
        </Button>
      </div>

      {isError && (
        <p className="text-sm text-destructive mb-4">
          Não foi possível carregar os tickets. Verifique sua sessão e tente novamente.
        </p>
      )}
      {isLoading && <p className="text-sm text-muted-foreground">Carregando...</p>}
      {!isLoading && !isError && tickets.length === 0 && (
        <p className="text-sm text-muted-foreground mb-4">
          {mostrarHistorico
            ? "Nenhum ticket registrado ainda."
            : "Nenhum ticket em aberto no momento. 🎉"}
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {tickets.map((t) => {
          const Icon = iconMap[t.categoria];
          const resolvido = t.status === "resolvido";
          const isResolving =
            resolverMutation.isPending && resolverMutation.variables?.id === t.id;
          const isSaving =
            salvarObservacaoMutation.isPending && salvarObservacaoMutation.variables?.id === t.id;
          return (
            <Card key={t.id} className={resolvido ? "opacity-60" : ""}>
              <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-3">
                <div className="flex items-center gap-3">
                  <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${colorMap[t.categoria]}`}>
                    <Icon className="h-5 w-5" />
                  </div>
                  <div>
                    <CardTitle className="text-base">{labelMap[t.categoria]}</CardTitle>
                    <p className="text-xs text-muted-foreground">Aberto em {t.abertura}</p>
                  </div>
                </div>
                {resolvido ? (
                  <Badge className="border-[var(--success-border)] bg-[var(--success-bg)] text-[var(--success-fg)] hover:bg-[var(--success-bg)]">Resolvido</Badge>
                ) : (
                  <Badge variant="outline">{t.status === "em_andamento" ? "Em andamento" : "Aberto"}</Badge>
                )}
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="text-xs uppercase text-muted-foreground mb-1">Imóvel</div>
                  <div className="text-sm font-medium">{t.imovel}</div>
                </div>
                <div>
                  <div className="text-xs uppercase text-muted-foreground mb-1">Descrição</div>
                  <p className="text-sm">{t.descricao}</p>
                </div>

                <div className="space-y-1.5">
                  <Label className="text-sm">Observações do prestador/vistoria</Label>
                  <Textarea
                    rows={3}
                    disabled={resolvido}
                    placeholder="Descreva o que foi verificado, materiais utilizados, próximos passos..."
                    value={observacoes[t.id] ?? t.observacao}
                    onChange={(e) =>
                      setObservacoes((prev) => ({ ...prev, [t.id]: e.target.value }))
                    }
                  />
                </div>

                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    className="flex-1"
                    disabled={resolvido || isSaving || isResolving}
                    onClick={() => salvarObservacaoMutation.mutate(t)}
                  >
                    {isSaving ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Salvando...
                      </>
                    ) : (
                      <>
                        <Save className="h-4 w-4 mr-2" /> Salvar Observação
                      </>
                    )}
                  </Button>

                  <Button
                    className="flex-1"
                    disabled={resolvido || isResolving || isSaving}
                    onClick={() => resolverMutation.mutate(t)}
                  >
                    {isResolving ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Resolvendo...
                      </>
                    ) : (
                      "Marcar como Resolvido"
                    )}
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}