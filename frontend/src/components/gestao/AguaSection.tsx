import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Info, Zap, Save, Loader2 } from "lucide-react";
import { PageHeader } from "./PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { supabase } from "@/lib/supabase";

const AGUA_QUERY_KEY = ["contratos-agua"] as const;

interface Leitura {
  contractId: string;
  imovel: string;
  inquilino: string;
  diaVencimento: number;
  consumoAtual: number | null; // valor já salvo no banco pro mês corrente, se existir
}

function primeiroDiaMesAtual(): string {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
}

function dataVencimentoMesAtual(diaVencimento: number): string {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), diaVencimento).toISOString().slice(0, 10);
}

async function fetchLeituras(): Promise<Leitura[]> {
  const { data: contratos, error: contratosError } = await supabase
    .from("contracts")
    .select("id, imovel_endereco, inquilino_nome, dia_vencimento")
    .eq("status", "ativo")
    .order("imovel_endereco");
  if (contratosError) throw contratosError;

  const mesAtual = primeiroDiaMesAtual();
  const { data: charges, error: chargesError } = await supabase
    .from("charges")
    .select("contract_id, consumo_m3")
    .eq("tipo", "agua")
    .eq("mes_referencia", mesAtual);
  if (chargesError) throw chargesError;

  const consumoPorContrato = new Map((charges ?? []).map((c) => [c.contract_id, c.consumo_m3]));

  return (contratos ?? []).map((c) => ({
    contractId: c.id,
    imovel: c.imovel_endereco,
    inquilino: c.inquilino_nome,
    diaVencimento: c.dia_vencimento,
    consumoAtual: consumoPorContrato.get(c.id) ?? null,
  }));
}

// Fórmula acordada: (consumo × R$ 6,18) + R$ 5,00 de taxa fixa.
function calcularValor(consumo: number): number {
  return consumo * 6.18 + 5;
}

export function AguaSection() {
  const queryClient = useQueryClient();
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [auto, setAuto] = useState(false);

  const { data: items = [], isLoading, isError } = useQuery({
    queryKey: AGUA_QUERY_KEY,
    queryFn: fetchLeituras,
  });

  // "AUTO" (integração com fonte digital de leitura) ainda não existe de
  // verdade — nenhum fornecedor foi integrado ainda. Mantido como
  // simulação visual explícita até essa integração existir de fato.
  const AUTO_LEITURAS_MOCK: Record<string, string> = {};

  const displayValue = (l: Leitura) => {
    if (auto) return AUTO_LEITURAS_MOCK[l.contractId] ?? "";
    return inputs[l.contractId] ?? (l.consumoAtual != null ? String(l.consumoAtual) : "");
  };

  const salvarMutation = useMutation({
    mutationFn: async (l: Leitura) => {
      const raw = inputs[l.contractId];
      const consumo = parseFloat(raw ?? "");
      if (!Number.isFinite(consumo) || consumo <= 0) {
        throw new Error("Informe um consumo válido antes de salvar");
      }
      const valor = calcularValor(consumo);

      const { error } = await supabase.from("charges").upsert(
        {
          contract_id: l.contractId,
          tipo: "agua",
          mes_referencia: primeiroDiaMesAtual(),
          data_vencimento: dataVencimentoMesAtual(l.diaVencimento),
          consumo_m3: consumo,
          valor_esperado: valor,
        },
        { onConflict: "contract_id,tipo,mes_referencia" },
      );
      if (error) throw error;
    },
    onSuccess: (_data, l) => {
      toast.success(`Leitura de ${l.imovel} salva`);
      queryClient.invalidateQueries({ queryKey: AGUA_QUERY_KEY });
    },
    onError: (error: Error) => {
      console.error("Erro ao salvar leitura de água:", error);
      toast.error(error.message || "Não foi possível salvar a leitura. Tente novamente.");
    },
  });

  return (
    <div>
      <PageHeader
        title="Consumo de Água"
        description="Registre as leituras mensais em m³. O valor é calculado em tempo real."
      />

      <Card className="mb-6">
        <CardContent className="flex items-center justify-between gap-4 py-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
              <Zap className="h-5 w-5 text-primary" />
            </div>
            <div>
              <div className="font-medium">Usar integração automática (Fonte Digital)</div>
              <div className="text-sm text-muted-foreground">
                Ainda não há fornecedor integrado — ligar aqui só simula o modo somente-leitura.
              </div>
            </div>
          </div>
          <Switch checked={auto} onCheckedChange={setAuto} />
        </CardContent>
      </Card>

      <div className="rounded-lg border bg-blue-50 border-blue-200 p-3 mb-6 flex items-start gap-2 text-sm text-blue-900">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <span>
          Fórmula aplicada: <strong>(Consumo × R$ 6,18) + R$ 5,00</strong>. A cobrança de água será
          disparada separadamente do aluguel.
        </span>
      </div>

      {isError && (
        <p className="text-sm text-destructive mb-4">
          Não foi possível carregar os imóveis. Verifique sua sessão e tente novamente.
        </p>
      )}

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-muted-foreground">
                <tr>
                  <th className="text-left px-6 py-3 font-medium">Imóvel</th>
                  <th className="text-left px-6 py-3 font-medium">Inquilino</th>
                  <th className="text-left px-6 py-3 font-medium w-48">Consumo (m³)</th>
                  <th className="text-right px-6 py-3 font-medium">Valor Cobrança</th>
                  <th className="text-right px-6 py-3 font-medium w-20"></th>
                </tr>
              </thead>
              <tbody>
                {isLoading && (
                  <tr>
                    <td colSpan={5} className="px-6 py-8 text-center text-muted-foreground">
                      Carregando...
                    </td>
                  </tr>
                )}
                {items.map((l) => {
                  const v = displayValue(l);
                  const n = parseFloat(v);
                  const total = Number.isFinite(n) && n > 0 ? calcularValor(n) : null;
                  const dirty = inputs[l.contractId] !== undefined && inputs[l.contractId] !== "";
                  const isPending =
                    salvarMutation.isPending &&
                    salvarMutation.variables?.contractId === l.contractId;
                  return (
                    <tr key={l.contractId} className="border-t hover:bg-muted/20">
                      <td className="px-6 py-4 font-medium">{l.imovel}</td>
                      <td className="px-6 py-4 text-muted-foreground">{l.inquilino}</td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2">
                          <Input
                            type="number"
                            min="0"
                            step="0.1"
                            placeholder="0"
                            value={v}
                            disabled={auto}
                            onChange={(e) =>
                              setInputs((prev) => ({ ...prev, [l.contractId]: e.target.value }))
                            }
                            className="max-w-[110px]"
                          />
                          {auto && (
                            <Badge variant="secondary" className="text-[10px]">
                              AUTO
                            </Badge>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-right">
                        {total !== null ? (
                          <span className="font-semibold text-primary">
                            R$ {total.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                          </span>
                        ) : (
                          <span className="text-muted-foreground text-xs">—</span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-right">
                        {!auto && dirty && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => salvarMutation.mutate(l)}
                            disabled={isPending}
                          >
                            {isPending ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Save className="h-4 w-4" />
                            )}
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground mt-3 italic">
        A cobrança de água será disparada separadamente do aluguel.
      </p>
    </div>
  );
}
