import { useState } from "react";
import { Info, Zap } from "lucide-react";
import { PageHeader } from "./PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";

interface Leitura {
  id: string;
  imovel: string;
  inquilino: string;
  consumo: string;
}

const iniciais: Leitura[] = [
  { id: "1", imovel: "Rua das Palmeiras, 245 — Apto 302", inquilino: "Ana Beatriz Souza", consumo: "" },
  { id: "2", imovel: "Av. Brasil, 1500 — Sala 8", inquilino: "Construtora Marca Ltda.", consumo: "" },
  { id: "3", imovel: "Rua Antônio Carlos, 89", inquilino: "Rafael Mendes", consumo: "" },
  { id: "4", imovel: "Rua Sete de Setembro, 1010", inquilino: "João Pedro Almeida", consumo: "" },
];

const AUTO_LEITURAS: Record<string, string> = {
  "1": "8",
  "2": "15",
  "3": "12",
  "4": "6",
};

export function AguaSection() {
  const [items, setItems] = useState(iniciais);
  const [auto, setAuto] = useState(false);

  const displayValue = (l: Leitura) => (auto ? AUTO_LEITURAS[l.id] ?? "" : l.consumo);

  const calc = (consumo: string) => {
    const n = parseFloat(consumo);
    if (!Number.isFinite(n) || n <= 0) return null;
    return n * 6.18 + 5;
  };

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
                Leituras coletadas automaticamente. Campos ficam somente-leitura.
              </div>
            </div>
          </div>
          <Switch checked={auto} onCheckedChange={setAuto} />
        </CardContent>
      </Card>

      <div className="rounded-lg border bg-blue-50 border-blue-200 p-3 mb-6 flex items-start gap-2 text-sm text-blue-900">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <span>Fórmula aplicada: <strong>(Consumo × R$ 6,18) + R$ 5,00</strong>. A cobrança de água será disparada separadamente do aluguel.</span>
      </div>

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
                </tr>
              </thead>
              <tbody>
                {items.map((l) => {
                  const v = displayValue(l);
                  const total = calc(v);
                  return (
                    <tr key={l.id} className="border-t hover:bg-muted/20">
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
                              setItems((prev) =>
                                prev.map((x) =>
                                  x.id === l.id ? { ...x, consumo: e.target.value } : x,
                                ),
                              )
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
