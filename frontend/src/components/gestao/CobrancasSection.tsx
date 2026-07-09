import { useState } from "react";
import { toast } from "sonner";
import { MessageCircle } from "lucide-react";
import { PageHeader } from "./PageHeader";
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

type Tipo = "" | "total" | "parcial" | "negado";

interface Negociacao {
  id: string;
  inquilino: string;
  imovel: string;
  telefone: string | null; // null = "Não Registrado"
  mes: string;
  valor: number;
  tipo: Tipo;
  valorNegociado: string;
  resolvida: boolean;
  resolvidoEm: string | null; // ISO timestamp de quando foi resolvida
}

// Dados retornados quando uma negociação é resolvida,
// prontos para você persistir no banco de dados.
export interface ResolucaoResult {
  id: string;
  inquilino: string;
  imovel: string;
  mes: string;
  valorOriginal: number;
  tipo: Exclude<Tipo, "">;
  valorNegociado: number | null; // null quando não se aplica (total/negado)
  resolvidoEm: string; // ISO timestamp
}

const iniciais: Negociacao[] = [
  {
    id: "n1",
    inquilino: "Rafael Mendes",
    imovel: "Rua Antônio Carlos, 89",
    telefone: "(81) 99123-4567",
    mes: "Junho/2026",
    valor: 1850,
    tipo: "",
    valorNegociado: "",
    resolvida: false,
    resolvidoEm: null,
  },
  {
    id: "n2",
    inquilino: "Construtora Marca Ltda.",
    imovel: "Av. Brasil, 1500 — Sala 8",
    telefone: null,
    mes: "Maio/2026",
    valor: 4200,
    tipo: "",
    valorNegociado: "",
    resolvida: false,
    resolvidoEm: null,
  },
  {
    id: "n3",
    inquilino: "João Pedro Almeida",
    imovel: "Rua Sete de Setembro, 1010",
    telefone: "(81) 98877-2233",
    mes: "Junho/2026",
    valor: 2100,
    tipo: "",
    valorNegociado: "",
    resolvida: false,
    resolvidoEm: null,
  },
];

interface CobrancasSectionProps {
  // Chamado toda vez que uma negociação é confirmada.
  // Use isso para persistir o resultado no seu banco de dados.
  onResolve?: (resultado: ResolucaoResult) => void;
}

export function CobrancasSection({ onResolve }: CobrancasSectionProps) {
  const [items, setItems] = useState(iniciais);

  const update = (id: string, patch: Partial<Negociacao>) =>
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, ...patch } : n)));

  const confirmar = (n: Negociacao) => {
    if (!n.tipo) return toast.error("Selecione o tipo de resolução");
    if (n.tipo === "parcial" && !n.valorNegociado)
      return toast.error("Informe o valor negociado");

    const resultado: ResolucaoResult = {
      id: n.id,
      inquilino: n.inquilino,
      imovel: n.imovel,
      mes: n.mes,
      valorOriginal: n.valor,
      tipo: n.tipo as Exclude<Tipo, "">,
      valorNegociado: n.tipo === "parcial" ? Number(n.valorNegociado) : null,
      resolvidoEm: new Date().toISOString(),
    };

    const msgs: Record<Exclude<Tipo, "">, string> = {
      total: `Olá ${n.inquilino}! Sua pendência de ${n.mes} foi perdoada integralmente. 🎉`,
      parcial: `Olá ${n.inquilino}! Fechamos um acordo em R$ ${n.valorNegociado} referente a ${n.mes}.`,
      negado: `Olá ${n.inquilino}, não foi possível conceder o desconto solicitado. Entre em contato.`,
    };
    const mensagem = msgs[n.tipo as Exclude<Tipo, "">];

    // TODO: chamar aqui a função real de envio de mensagem via WhatsApp
    // Ex: await enviarMensagemWhatsApp({ telefone: n.telefoneInquilino, mensagem });
    // O toast abaixo é só uma simulação visual e deve ser mantido (ou ajustado)
    // para refletir o resultado real do envio (sucesso/erro).
    toast.success("WhatsApp enviado ao inquilino", {
      description: mensagem,
      icon: <MessageCircle className="h-4 w-4" />,
    });

    // Envia os dados decididos para quem estiver usando o componente
    // (ex: para salvar no banco de dados)
    onResolve?.(resultado);

    // Marca como resolvida (o card fica visível por 24h antes de sumir)
    update(n.id, { resolvida: true, resolvidoEm: resultado.resolvidoEm });
  };

  return (
    <div>
      <PageHeader
        title="Cobranças em Negociação"
        description="Gerencie perdões, descontos parciais e negações."
      />
      <div className="grid gap-4">
        {items.map((n) => (
          <Card key={n.id} className={n.resolvida ? "opacity-70" : ""}>
            <CardHeader className="flex flex-row items-start justify-between space-y-0">
              <div>
                <CardTitle className="text-base">{n.inquilino}</CardTitle>
                <p className="text-sm text-muted-foreground mt-1">{n.imovel}</p>
              </div>
              {n.resolvida ? (
                <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
                  Resolvida
                </Badge>
              ) : (
                <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100">
                  Em Negociação
                </Badge>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <div className="text-xs uppercase text-muted-foreground">Mês de Referência</div>
                  <div className="font-medium">{n.mes}</div>
                </div>
                <div>
                  <div className="text-xs uppercase text-muted-foreground">Valor Original</div>
                  <div className="font-semibold text-lg">
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

              {!n.resolvida && (
                <div className="grid md:grid-cols-[1fr,1fr,auto] gap-3 items-end pt-2 border-t">
                  <div className="space-y-1.5">
                    <Label>Tipo de Resolução</Label>
                    <Select
                      value={n.tipo}
                      onValueChange={(v) => update(n.id, { tipo: v as Tipo })}
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
                  {n.tipo === "parcial" ? (
                    <div className="space-y-1.5">
                      <Label>Valor Negociado (R$)</Label>
                      <Input
                        type="number"
                        placeholder="0,00"
                        value={n.valorNegociado}
                        onChange={(e) => update(n.id, { valorNegociado: e.target.value })}
                      />
                    </div>
                  ) : (
                    <div />
                  )}
                  <Button onClick={() => confirmar(n)}>Confirmar Resolução</Button>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
        {items.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-8">
            Nenhuma cobrança pendente de negociação.
          </p>
        )}
      </div>
    </div>
  );
}