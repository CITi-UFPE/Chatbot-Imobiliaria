import { useState } from "react";
import { toast } from "sonner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Zap, Droplet, Hammer, Paintbrush, Wrench, CheckCircle2, Save, Loader2, ClipboardList, AlertCircle } from "lucide-react";
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

interface Ticket {
  id: string;
  categoria: MaintenanceCategoria;
  descricao: string;
  imovel: string;
  abertura: string; // já formatada pt-BR
  observacao: string;
  status: MaintenanceStatus;
}

async function fetchTickets(): Promise<Ticket[]> {
  const { data, error } = await supabase
    .from("maintenance_tickets")
    .select("id, categoria, descricao, observacao, status, data_abertura, contracts(imovel_endereco)")
    .order("data_abertura", { ascending: false });
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

  const { data: tickets = [], isLoading, isError } = useQuery({
    queryKey: MANUTENCAO_QUERY_KEY,
    queryFn: fetchTickets,
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
          value={tickets.length}
          sublabel="no total"
        />
        <StatTile
          tone="c"
          icon={<AlertCircle className="h-5 w-5" />}
          label="Abertos"
          value={tickets.filter((t) => t.status !== "resolvido").length}
          sublabel="aguardando resolução"
        />
        <StatTile
          tone="d"
          icon={<CheckCircle2 className="h-5 w-5" />}
          label="Resolvidos"
          value={tickets.filter((t) => t.status === "resolvido").length}
          sublabel="concluídos"
        />
      </div>

      {isError && (
        <p className="text-sm text-destructive mb-4">
          Não foi possível carregar os tickets. Verifique sua sessão e tente novamente.
        </p>
      )}
      {isLoading && <p className="text-sm text-muted-foreground">Carregando...</p>}

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