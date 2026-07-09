import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  CalendarClock,
  TrendingUp,
  Sparkles,
  Wrench,
  Gift,
} from "lucide-react";
import { PageHeader } from "./PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Separator } from "@/components/ui/separator";

type Decisao = "" | "sugerido" | "manual" | "encerrar";

interface Contrato {
  id: string;
  inquilino: string;
  aniversario: string;
  valorAtual: number;
  reajuste: number; // %
  janela: "D-60 Renovação" | "D-30 Reajuste";
  decisao: Decisao;
  valorManual: string;
  status: "pendente" | "renovado" | "encerrado";
}

interface ContratoAtivo {
  id: string;
  inquilino: string;
  imovel: string;
  valorAtual: number;
}

interface Aniversario {
  id: string;
  inquilino: string;
  aniversario: string;
  diasRestantes: number;
  valorAtual: number;
  taxa: number; // %
  aplicado: boolean;
  modo: "sugerido" | "manual";
  valorManual: string;
}

const contratosAtivosIniciais: ContratoAtivo[] = [
  {
    id: "c1",
    inquilino: "Ana Beatriz Souza",
    imovel: "Apt. 302 — Ed. Aurora",
    valorAtual: 2500,
  },
  {
    id: "c2",
    inquilino: "Construtora Marca Ltda.",
    imovel: "Sala 12 — Centro Empresarial",
    valorAtual: 4200,
  },
  {
    id: "c3",
    inquilino: "João Pedro Almeida",
    imovel: "Casa 05 — Vila Nova",
    valorAtual: 2100,
  },
  {
    id: "c4",
    inquilino: "Marcela Ribeiro",
    imovel: "Apt. 101 — Ed. Jardim",
    valorAtual: 1850,
  },
];

const aniversariosIniciais: Aniversario[] = [
  {
    id: "a1",
    inquilino: "Carlos Menezes",
    aniversario: "07/08/2026",
    diasRestantes: 30,
    valorAtual: 3200,
    taxa: 5.4,
    aplicado: false,
    modo: "sugerido",
    valorManual: "",
  },
  {
    id: "a2",
    inquilino: "Fernanda Lopes",
    aniversario: "18/08/2026",
    diasRestantes: 21,
    valorAtual: 1900,
    taxa: 4.7,
    aplicado: false,
    modo: "sugerido",
    valorManual: "",
  },
];

const iniciais: Contrato[] = [
  {
    id: "r1",
    inquilino: "Ana Beatriz Souza",
    aniversario: "05/09/2026",
    valorAtual: 2500,
    reajuste: 4.8,
    janela: "D-60 Renovação",
    decisao: "",
    valorManual: "",
    status: "pendente",
  },
  {
    id: "r2",
    inquilino: "Construtora Marca Ltda.",
    aniversario: "12/08/2026",
    valorAtual: 4200,
    reajuste: 6.2,
    janela: "D-30 Reajuste",
    decisao: "",
    valorManual: "",
    status: "pendente",
  },
  {
    id: "r3",
    inquilino: "João Pedro Almeida",
    aniversario: "20/09/2026",
    valorAtual: 2100,
    reajuste: 5.1,
    janela: "D-60 Renovação",
    decisao: "",
    valorManual: "",
    status: "pendente",
  },
];

const brl = (v: number) =>
  `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;

/* -------------------- Seção 1: Reajustes Manuais -------------------- */

function ReajustesManuaisSection({
  contratos,
  onReajustar,
}: {
  contratos: ContratoAtivo[];
  onReajustar: (id: string, novoValor: number) => void;
}) {
  const [inputs, setInputs] = useState<Record<string, string>>({});

  const setInput = (id: string, v: string) =>
    setInputs((prev) => ({ ...prev, [id]: v }));

  const aplicar = (c: ContratoAtivo) => {
    const raw = (inputs[c.id] ?? "").replace(",", ".");
    const novo = parseFloat(raw);
    if (!Number.isFinite(novo) || novo <= 0) {
      return toast.error("Informe um valor válido");
    }
    onReajustar(c.id, novo);
    setInput(c.id, "");
    toast.success("Reajuste manual aplicado", {
      description: `${c.inquilino}: ${brl(c.valorAtual)} → ${brl(novo)}`,
    });
  };

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

      {contratos.length === 0 ? (
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
                  <div>
                    <CardTitle className="text-base">{c.inquilino}</CardTitle>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {c.imovel}
                    </p>
                  </div>
                  <Badge variant="secondary">Ativo</Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="rounded-lg bg-muted/30 p-3">
                  <div className="text-xs uppercase text-muted-foreground">
                    Valor atual
                  </div>
                  <div className="font-semibold">{brl(c.valorAtual)}</div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`man-${c.id}`}>Novo valor (R$)</Label>
                  <div className="flex gap-2">
                    <Input
                      id={`man-${c.id}`}
                      type="number"
                      placeholder="0,00"
                      value={inputs[c.id] ?? ""}
                      onChange={(e) => setInput(c.id, e.target.value)}
                    />
                    <Button onClick={() => aplicar(c)}>Aplicar</Button>
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

/* -------------------- Seção 2: Reajustes de Aniversário -------------------- */

function ReajustesAniversarioSection({
  items,
  onUpdate,
  onAplicar,
}: {
  items: Aniversario[];
  onUpdate: (id: string, patch: Partial<Aniversario>) => void;
  onAplicar: (a: Aniversario) => void;
}) {
  const pendentes = items.filter((a) => !a.aplicado);

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

      {pendentes.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            Nenhum reajuste de aniversário pendente.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {pendentes.map((a) => {
            const sugerido = a.valorAtual * (1 + a.taxa / 100);
            const manualNum = parseFloat(a.valorManual.replace(",", "."));
            return (
              <Card key={a.id}>
                <CardHeader className="flex flex-row items-start justify-between space-y-0">
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
                      <Sparkles className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <CardTitle className="text-base">{a.inquilino}</CardTitle>
                      <p className="text-xs text-muted-foreground">
                        Aniversário: {a.aniversario}
                      </p>
                    </div>
                  </div>
                  <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100">
                    Faltam {a.diasRestantes} {a.diasRestantes === 1 ? "dia" : "dias"}
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm bg-muted/30 rounded-lg p-4">
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">
                        Valor atual
                      </div>
                      <div className="font-semibold">{brl(a.valorAtual)}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">
                        Taxa do contrato
                      </div>
                      <div className="font-semibold flex items-center gap-1 text-emerald-700">
                        <TrendingUp className="h-3.5 w-3.5" />
                        {a.taxa.toFixed(2)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">
                        Valor sugerido
                      </div>
                      <div className="font-semibold text-primary">
                        {brl(sugerido)}
                      </div>
                    </div>
                  </div>

                  <RadioGroup
                    value={a.modo}
                    onValueChange={(v) =>
                      onUpdate(a.id, { modo: v as "sugerido" | "manual" })
                    }
                    className="grid gap-2"
                  >
                    <label className="flex items-center gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40">
                      <RadioGroupItem value="sugerido" id={`${a.id}-s`} />
                      <span className="text-sm">
                        Aceitar valor sugerido ({brl(sugerido)})
                      </span>
                    </label>
                    <label className="flex items-center gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40">
                      <RadioGroupItem value="manual" id={`${a.id}-m`} />
                      <span className="text-sm">Alterar manualmente</span>
                    </label>
                  </RadioGroup>

                  {a.modo === "manual" && (
                    <div className="space-y-1.5">
                      <Label>Novo valor (R$)</Label>
                      <Input
                        type="number"
                        placeholder="0,00"
                        value={a.valorManual}
                        onChange={(e) =>
                          onUpdate(a.id, { valorManual: e.target.value })
                        }
                        className="max-w-xs"
                      />
                    </div>
                  )}

                  <div className="flex justify-end">
                    <Button
                      onClick={() => onAplicar(a)}
                      disabled={
                        a.modo === "manual" &&
                        (!Number.isFinite(manualNum) || manualNum <= 0)
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

/* -------------------- Seção 3: Renovações (existente) -------------------- */

export function RenovacoesSection() {
  const [items, setItems] = useState(iniciais);
  const [contratosAtivos, setContratosAtivos] = useState(contratosAtivosIniciais);
  const [aniversarios, setAniversarios] = useState(aniversariosIniciais);

  const update = (id: string, patch: Partial<Contrato>) =>
    setItems((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));

  const updateAniv = (id: string, patch: Partial<Aniversario>) =>
    setAniversarios((prev) =>
      prev.map((a) => (a.id === id ? { ...a, ...patch } : a)),
    );

  const aplicarAniversario = (a: Aniversario) => {
    const sugerido = a.valorAtual * (1 + a.taxa / 100);
    const novo =
      a.modo === "sugerido"
        ? sugerido
        : parseFloat(a.valorManual.replace(",", "."));

    if (!Number.isFinite(novo) || novo <= 0) {
      return toast.error("Informe um valor válido");
    }

    setContratosAtivos((prev) =>
      prev.map((c) =>
        c.inquilino === a.inquilino ? { ...c, valorAtual: novo } : c,
      ),
    );
    updateAniv(a.id, { aplicado: true });
    toast.success("Reajuste de aniversário aplicado", {
      description: `${a.inquilino}: ${brl(a.valorAtual)} → ${brl(novo)}`,
    });
  };

  const reajustarManual = (id: string, novo: number) => {
    setContratosAtivos((prev) =>
      prev.map((c) => (c.id === id ? { ...c, valorAtual: novo } : c)),
    );
  };

  const confirmar = (c: Contrato) => {
    if (!c.decisao) return toast.error("Selecione uma decisão");

    if (c.decisao === "encerrar") {
      update(c.id, { status: "encerrado", valorAtual: c.valorAtual });
      toast.success("Contrato encerrado", {
        description: `Fluxo de desativação iniciado para ${c.inquilino}.`,
      });
      return;
    }

    const sugerido = c.valorAtual * (1 + c.reajuste / 100);
    const novoValor =
      c.decisao === "sugerido"
        ? sugerido
        : parseFloat(c.valorManual.replace(",", "."));

    if (c.decisao === "manual" && (!Number.isFinite(novoValor) || novoValor <= 0)) {
      return toast.error("Informe um valor manual válido");
    }

    update(c.id, { status: "renovado", valorAtual: novoValor });
    toast.success("Renovação confirmada", {
      description: `Valor atualizado para ${brl(novoValor)} no próximo ciclo.`,
    });
  };

  const contratosOrdenados = useMemo(
    () => [...contratosAtivos].sort((a, b) => a.inquilino.localeCompare(b.inquilino)),
    [contratosAtivos],
  );

  return (
    <div className="space-y-10">
      <PageHeader
        title="Renovações e Reajustes"
        description="Reajustes manuais a qualquer momento, reajustes automáticos de aniversário e renovações em janela de alerta — tudo em um único painel."
      />

      <ReajustesManuaisSection
        contratos={contratosOrdenados}
        onReajustar={reajustarManual}
      />

      <Separator />

      <ReajustesAniversarioSection
        items={aniversarios}
        onUpdate={updateAniv}
        onAplicar={aplicarAniversario}
      />

      <Separator />

      <section>
        <div className="flex items-center gap-2 mb-3">
          <CalendarClock className="h-4 w-4 text-primary" />
          <h2 className="text-lg font-semibold">Renovação</h2>
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          Contratos em janela de alerta (D-60 renovação, D-30 reajuste). Registre a
          decisão administrativa — o valor é atualizado no contrato existente.
        </p>

        <div className="grid gap-4">
          {items.map((c) => {
            const sugerido = c.valorAtual * (1 + c.reajuste / 100);
            const encerrado = c.status === "encerrado";
            const renovado = c.status === "renovado";
            const done = encerrado || renovado;

            return (
              <Card key={c.id}>
                <CardHeader className="flex flex-row items-start justify-between space-y-0">
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
                      <CalendarClock className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <CardTitle className="text-base">{c.inquilino}</CardTitle>
                      <p className="text-xs text-muted-foreground">
                        Aniversário: {c.aniversario}
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <Badge
                      className={
                        c.janela === "D-60 Renovação"
                          ? "bg-blue-100 text-blue-700 hover:bg-blue-100"
                          : "bg-amber-100 text-amber-700 hover:bg-amber-100"
                      }
                    >
                      {c.janela}
                    </Badge>
                    {renovado && (
                      <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
                        Renovado
                      </Badge>
                    )}
                    {encerrado && <Badge variant="destructive">Encerrado</Badge>}
                  </div>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm bg-muted/30 rounded-lg p-4">
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">
                        Valor Atual
                      </div>
                      <div className="font-semibold">{brl(c.valorAtual)}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">
                        Reajuste
                      </div>
                      <div className="font-semibold flex items-center gap-1 text-emerald-700">
                        <TrendingUp className="h-3.5 w-3.5" />
                        {c.reajuste.toFixed(2)}%
                      </div>
                    </div>
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">
                        Valor Sugerido
                      </div>
                      <div className="font-semibold text-primary">
                        {brl(sugerido)}
                      </div>
                    </div>
                  </div>

                  {!done && (
                    <div className="space-y-4">
                      <Label>Decisão</Label>
                      <RadioGroup
                        value={c.decisao}
                        onValueChange={(v) => update(c.id, { decisao: v as Decisao })}
                        className="grid gap-2"
                      >
                        <label className="flex items-center gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40">
                          <RadioGroupItem value="sugerido" id={`${c.id}-s`} />
                          <span className="text-sm">
                            Renovar com valor sugerido ({brl(sugerido)})
                          </span>
                        </label>
                        <label className="flex items-center gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40">
                          <RadioGroupItem value="manual" id={`${c.id}-m`} />
                          <span className="text-sm">
                            Renovar com valor ajustado manualmente
                          </span>
                        </label>
                        <label className="flex items-center gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40">
                          <RadioGroupItem value="encerrar" id={`${c.id}-e`} />
                          <span className="text-sm">Encerrar contrato</span>
                        </label>
                      </RadioGroup>

                      {c.decisao === "manual" && (
                        <div className="space-y-1.5">
                          <Label>Novo valor (R$)</Label>
                          <Input
                            type="number"
                            placeholder="0,00"
                            value={c.valorManual}
                            onChange={(e) =>
                              update(c.id, { valorManual: e.target.value })
                            }
                            className="max-w-xs"
                          />
                        </div>
                      )}

                      <div className="flex justify-end">
                        <Button
                          onClick={() => confirmar(c)}
                          variant={
                            c.decisao === "encerrar" ? "destructive" : "default"
                          }
                        >
                          {c.decisao === "encerrar"
                            ? "Confirmar Encerramento"
                            : "Confirmar Renovação"}
                        </Button>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>
    </div>
  );
}
