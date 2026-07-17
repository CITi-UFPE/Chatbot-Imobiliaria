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

// Estado local só do formulário de resolução (tipo escolhido, valor digitado)
// — não é dado do banco, por isso continua em useState em vez de query.
interface FormState {
  tipo: Tipo;
  valorNegociado: string;
}

export function CobrancasSection() {
  const queryClient = useQueryClient();
  const [forms, setForms] = useState<Record<string, FormState>>({});

  const { data: items = [], isLoading, isError } = useQuery({
    queryKey: COBRANCAS_QUERY_KEY,
    queryFn: fetchNegociacoes,
  });

  const getForm = (id: string): FormState => forms[id] ?? { tipo: "", valorNegociado: "" };
  const updateForm = (id: string, patch: Partial<FormState>) =>
    setForms((prev) => ({ ...prev, [id]: { ...getForm(id), ...patch } }));

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
      const { error: chargeError } = await supabase
        .from("charges")
        .update({ status: novoStatusCharge })
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

  return (
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
  );
}
