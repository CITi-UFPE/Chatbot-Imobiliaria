import { useState } from "react";
import { toast } from "sonner";
import { Zap, Droplet, Hammer, CheckCircle2 } from "lucide-react";
import { PageHeader } from "./PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";

type Categoria = "Elétrica" | "Hidráulica" | "Estrutural";

interface Ticket {
  id: string;
  categoria: Categoria;
  descricao: string;
  imovel: string;
  abertura: string;
  observacoes: string;
  resolvido: boolean;
}

const iniciais: Ticket[] = [
  {
    id: "t1",
    categoria: "Elétrica",
    descricao: "Curto-circuito no disjuntor da cozinha após chuva forte.",
    imovel: "Rua das Palmeiras, 245 — Apto 302",
    abertura: "05/07/2026",
    observacoes: "",
    resolvido: false,
  },
  {
    id: "t2",
    categoria: "Hidráulica",
    descricao: "Vazamento no registro geral, água acumulando na área de serviço.",
    imovel: "Av. Brasil, 1500 — Sala 8",
    abertura: "07/07/2026",
    observacoes: "",
    resolvido: false,
  },
  {
    id: "t3",
    categoria: "Estrutural",
    descricao: "Infiltração no teto do quarto principal, mancha crescendo.",
    imovel: "Rua Sete de Setembro, 1010",
    abertura: "03/07/2026",
    observacoes: "",
    resolvido: false,
  },
];

const iconMap: Record<Categoria, React.ComponentType<{ className?: string }>> = {
  Elétrica: Zap,
  Hidráulica: Droplet,
  Estrutural: Hammer,
};

const colorMap: Record<Categoria, string> = {
  Elétrica: "bg-amber-100 text-amber-700",
  Hidráulica: "bg-sky-100 text-sky-700",
  Estrutural: "bg-orange-100 text-orange-700",
};

export function ManutencaoSection() {
  const [tickets, setTickets] = useState(iniciais);

  const resolver = (id: string) => {
    setTickets((prev) => prev.map((t) => (t.id === id ? { ...t, resolvido: true } : t)));
    toast.success("Ticket arquivado como resolvido", {
      icon: <CheckCircle2 className="h-4 w-4" />,
    });
  };

  return (
    <div>
      <PageHeader
        title="Manutenção"
        description="Tickets abertos automaticamente pelo sistema A3. Registre observações do prestador e feche quando concluído."
      />

      <div className="grid gap-4 md:grid-cols-2">
        {tickets.map((t) => {
          const Icon = iconMap[t.categoria];
          return (
            <Card key={t.id} className={t.resolvido ? "opacity-60" : ""}>
              <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-3">
                <div className="flex items-center gap-3">
                  <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${colorMap[t.categoria]}`}>
                    <Icon className="h-5 w-5" />
                  </div>
                  <div>
                    <CardTitle className="text-base">{t.categoria}</CardTitle>
                    <p className="text-xs text-muted-foreground">Aberto em {t.abertura}</p>
                  </div>
                </div>
                {t.resolvido ? (
                  <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">Resolvido</Badge>
                ) : (
                  <Badge variant="outline">Aberto</Badge>
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
                    disabled={t.resolvido}
                    placeholder="Descreva o que foi verificado, materiais utilizados, próximos passos..."
                    value={t.observacoes}
                    onChange={(e) =>
                      setTickets((prev) =>
                        prev.map((x) => (x.id === t.id ? { ...x, observacoes: e.target.value } : x)),
                      )
                    }
                  />
                </div>

                <Button
                  className="w-full"
                  disabled={t.resolvido}
                  onClick={() => resolver(t.id)}
                >
                  Marcar como Resolvido
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
