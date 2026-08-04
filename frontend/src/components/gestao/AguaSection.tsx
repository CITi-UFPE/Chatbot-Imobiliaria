import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Info,
  Loader2,
  ScanSearch,
  CloudUpload,
  Upload,
  FileText,
  AlertCircle,
  CheckCircle2,
  Search,
} from "lucide-react";
import { PageHeader } from "./PageHeader";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import { supabase } from "@/lib/supabase";

const AGUA_QUERY_KEY = ["contratos-agua"] as const;

export function AguaSection() {
  return (
    <div>
      <PageHeader
        title="Consumo de Água"
        description="Envie a conta de água em PDF e deixe o sistema fazer o resto."
      />

      <div className="rounded-lg border bg-[var(--info-bg)] border-[var(--info-border)] p-3 mb-6 flex items-start gap-2 text-sm text-[var(--info-strong)]">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <span>
          Como funciona: envie o PDF da conta de água recebida do condomínio. O sistema lê o
          documento sozinho e já sugere para qual imóvel ela pertence. Você confere os dados
          ao lado do PDF e só confirma quando estiver tudo certo — nada é lançado sem a sua
          aprovação.
        </span>
      </div>

      <ComprovanteAguaUpload />
    </div>
  );
}


/* ============================================================
   Fluxo Híbrido — Leitura de Água por Comprovante (IA + Humano)
   ============================================================
   Upload de 1 PDF por vez -> IA extrai os campos e sugere o
   contrato correspondente -> tela de conferência com o PDF
   sempre visível ao lado dos dados -> confirmação humana grava
   em `charges` (tipo = 'agua').
*/

const CONTRATOS_ATIVOS_QUERY_KEY = ["contratos-ativos-para-match"] as const;

interface ContratoAtivo {
  id: string;
  imovel_identificacao: string;
  imovel_endereco: string;
  dia_vencimento: number;
}

async function fetchContratosAtivosParaMatch(): Promise<ContratoAtivo[]> {
  const { data, error } = await supabase
    .from("contracts")
    .select("id, imovel_identificacao, imovel_endereco, dia_vencimento")
    .eq("status", "ativo")
    .order("imovel_endereco");
  if (error) throw error;
  return data ?? [];
}

interface CandidatoContrato {
  contractId: string;
  confianca: number; // 0 a 1
  justificativa: string;
}

interface ExtracaoContaAguaResult {
  condominio: string;
  apartamento: string;
  bloco: string | null;
  periodoInicio: string; // YYYY-MM-DD
  periodoFim: string; // YYYY-MM-DD
  valorTotal: number;
  candidatos: CandidatoContrato[];
}

type CandidatoValido = CandidatoContrato & ContratoAtivo;

// ==========================================================
// 🔌 PONTO DE INTEGRAÇÃO: extração + correspondência via IA
// ==========================================================
// Envia o PDF da conta de água + a lista de contratos ativos
// (id, imovel_identificacao, imovel_endereco) pro backend, que
// chama a Claude API para ler o documento e raciocinar sobre a
// correspondência num único passo, conforme o fluxo híbrido.
async function extrairEIdentificarContrato(
  arquivo: File,
  contratosAtivos: ContratoAtivo[],
): Promise<ExtracaoContaAguaResult> {
  const formData = new FormData();
  formData.append("arquivo", arquivo);
  formData.append(
    "contratos",
    JSON.stringify(
      contratosAtivos.map((c) => ({
        id: c.id,
        imovel_identificacao: c.imovel_identificacao,
        imovel_endereco: c.imovel_endereco,
      })),
    ),
  );

  const apiUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5 * 60 * 1000);
  const response = await fetch(`${apiUrl}/charges/agua/extrair`, {
    method: "POST",
    body: formData,
    signal: controller.signal,
  }).finally(() => clearTimeout(timeout));

  if (!response.ok) {
    const erro = await response.json().catch(() => null);
    throw new Error(erro?.detail ?? "Falha ao processar a conta de água.");
  }

  return response.json();
}

// Limiares para classificar o cenário de correspondência — ver a
// "Regra de decisão" do fluxo híbrido. Ajustável conforme a
// qualidade real das pontuações devolvidas pela IA. A pontuação em si
// nunca é mostrada ao usuário (ver CandidatoCard) — só orienta qual
// cenário de conferência é exibido.
const CONFIANCA_MINIMA = 0.7;
const DIFERENCA_MINIMA_DESEMPATE = 0.2;

type CenarioMatch = "confiavel" | "ambiguidade" | "lista_completa";

function classificarCenario(candidatos: CandidatoValido[]): CenarioMatch {
  if (candidatos.length === 0 || candidatos.length >= 3) return "lista_completa";
  if (candidatos.length === 1) {
    return candidatos[0].confianca >= CONFIANCA_MINIMA ? "confiavel" : "lista_completa";
  }
  const [primeiro, segundo] = [...candidatos].sort((a, b) => b.confianca - a.confianca);
  if (
    primeiro.confianca >= CONFIANCA_MINIMA &&
    primeiro.confianca - segundo.confianca >= DIFERENCA_MINIMA_DESEMPATE
  ) {
    return "confiavel";
  }
  return "ambiguidade";
}

function primeiroDiaDoMes(dataISO: string): string {
  const [ano, mes] = dataISO.split("-");
  return `${ano}-${mes}-01`;
}

function dataVencimentoDoMes(diaVencimento: number, mesReferenciaISO: string): string {
  const [ano, mes] = mesReferenciaISO.split("-");
  return `${ano}-${mes}-${String(diaVencimento).padStart(2, "0")}`;
}

function formatarDataBR(dataISO: string | undefined): string {
  if (!dataISO) return "";
  const [ano, mes, dia] = dataISO.split("-");
  return `${dia}/${mes}/${ano}`;
}

function diferencaEmDias(dataInicioISO: string, dataFimISO: string): number {
  // Meio-dia UTC fixo pras duas pontas, pra não sofrer com fuso horário nem
  // com horário de verão na subtração.
  const inicio = new Date(`${dataInicioISO}T00:00:00Z`);
  const fim = new Date(`${dataFimISO}T00:00:00Z`);
  return Math.round((fim.getTime() - inicio.getTime()) / (1000 * 60 * 60 * 24));
}

interface CamposExtraidos {
  condominio: string;
  apartamento: string;
  bloco: string;
  periodoInicio: string;
  periodoFim: string;
  valorTotal: number;
}

export function ComprovanteAguaUpload() {
  const queryClient = useQueryClient();
  const [step, setStep] = useState<1 | 2>(1);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);

  const [campos, setCampos] = useState<CamposExtraidos>({
    condominio: "",
    apartamento: "",
    bloco: "",
    periodoInicio: "",
    periodoFim: "",
    valorTotal: 0,
  });
  const [candidatos, setCandidatos] = useState<CandidatoValido[]>([]);
  const [cenario, setCenario] = useState<CenarioMatch>("lista_completa");
  const [buscaManual, setBuscaManual] = useState("");
  const [modoBuscaManual, setModoBuscaManual] = useState(false);
  const [contratoSelecionadoId, setContratoSelecionadoId] = useState<string | null>(null);
  // Preenchido só quando a data de vencimento calculada já passou — controla
  // o AlertDialog de confirmação antes de gravar a cobrança como atrasada.
  const [contaVencidaPendente, setContaVencidaPendente] = useState<{ dataVencimento: string } | null>(
    null,
  );

  const { data: contratosAtivos = [] } = useQuery({
    queryKey: CONTRATOS_ATIVOS_QUERY_KEY,
    queryFn: fetchContratosAtivosParaMatch,
  });

  const contratoSelecionado = contratosAtivos.find((c) => c.id === contratoSelecionadoId) ?? null;

  const resetar = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setStep(1);
    setFile(null);
    setPreviewUrl(null);
    setCampos({
      condominio: "",
      apartamento: "",
      bloco: "",
      periodoInicio: "",
      periodoFim: "",
      valorTotal: 0,
    });
    setCandidatos([]);
    setCenario("lista_completa");
    setBuscaManual("");
    setModoBuscaManual(false);
    setContratoSelecionadoId(null);
    setContaVencidaPendente(null);
  };

  const handleFile = (f: File | null) => {
    if (!f) return;
    if (f.type !== "application/pdf") {
      toast.error("Envie o arquivo em PDF");
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(f);
    setPreviewUrl(URL.createObjectURL(f));
  };

  const processarArquivo = async () => {
    if (!file) {
      toast.error("Selecione o PDF da conta de água");
      return;
    }
    if (contratosAtivos.length === 0) {
      toast.error("Nenhum contrato ativo cadastrado para associar a leitura");
      return;
    }
    setLoading(true);
    try {
      const resultado = await extrairEIdentificarContrato(file, contratosAtivos);

      // Descarta candidatos cujo id não existe mais em contracts —
      // tratado como ausência de correspondência confiável.
      const candidatosValidos: CandidatoValido[] = resultado.candidatos
        .map((c) => {
          const contrato = contratosAtivos.find((ct) => ct.id === c.contractId);
          return contrato ? { ...c, ...contrato } : null;
        })
        .filter((c): c is CandidatoValido => c !== null);

      const cenarioDetectado = classificarCenario(candidatosValidos);
      const ordenados = [...candidatosValidos].sort((a, b) => b.confianca - a.confianca);

      setCampos({
        condominio: resultado.condominio,
        apartamento: resultado.apartamento,
        bloco: resultado.bloco ?? "",
        periodoInicio: resultado.periodoInicio,
        periodoFim: resultado.periodoFim,
        valorTotal: resultado.valorTotal,
      });
      setCandidatos(candidatosValidos);
      setCenario(cenarioDetectado);
      setModoBuscaManual(cenarioDetectado === "lista_completa");
      setContratoSelecionadoId(cenarioDetectado === "confiavel" ? ordenados[0]?.contractId ?? null : null);
      setBuscaManual("");
      setStep(2);
    } catch (error) {
      console.error("Erro ao processar conta de água:", error);
      toast.error(
        error instanceof Error ? error.message : "Não foi possível processar o documento. Tente novamente.",
      );
    } finally {
      setLoading(false);
    }
  };

  const confirmarMutation = useMutation({
    mutationFn: async (opts: { statusForcado?: "atrasado" } = {}) => {
      if (!contratoSelecionado) throw new Error("Selecione o contrato correspondente");
      if (!campos.valorTotal || campos.valorTotal <= 0) throw new Error("Informe um valor válido");
      if (!campos.periodoInicio) throw new Error("Informe o período de referência");

      const mesReferencia = primeiroDiaDoMes(campos.periodoInicio);
      const dataVencimento = dataVencimentoDoMes(contratoSelecionado.dia_vencimento, mesReferencia);

      // Quando o usuário confirma o lançamento de uma conta já vencida (ver
      // handleConfirmarClick), calculamos os dias de atraso na hora — reflete
      // o atraso já existente no momento do lançamento, não é recalculado depois.
      const diasAtraso =
        opts.statusForcado === "atrasado"
          ? Math.max(0, diferencaEmDias(dataVencimento, new Date().toISOString().slice(0, 10)))
          : 0;

      // Grava apenas a cobrança esperada do mês, com base na leitura da
      // conta de água. valor_identificado, comprovante_url e
      // data_identificada_comprovante ficam nulos de propósito: só são
      // preenchidos depois, quando o inquilino enviar o comprovante de
      // pagamento (fluxo separado). data_pagamento e mensagem_estagio
      // também ficam nulos. status assume o default 'pendente' da tabela,
      // a não ser que o usuário tenha confirmado o lançamento de uma conta
      // já vencida (ver handleConfirmarClick) — nesse caso grava 'atrasado'
      // e os dias_atraso já calculados.
      const { error: insertError } = await supabase.from("charges").insert({
        contract_id: contratoSelecionado.id,
        tipo: "agua",
        mes_referencia: mesReferencia,
        valor_esperado: campos.valorTotal,
        data_vencimento: dataVencimento,
        ...(opts.statusForcado
          ? { status: opts.statusForcado, dias_atraso: diasAtraso }
          : {}),
      });

      if (insertError) {
        if (insertError.code === "23505") {
          throw new Error("Já existe uma cobrança de água lançada para este imóvel neste período.");
        }
        throw insertError;
      }
    },
    onSuccess: () => {
      toast.success(`Leitura de água de ${contratoSelecionado?.imovel_endereco} lançada com sucesso`);
      queryClient.invalidateQueries({ queryKey: AGUA_QUERY_KEY });
      resetar();
    },
    onError: (error: Error) => {
      console.error("Erro ao confirmar leitura de água:", error);
      toast.error(error.message || "Não foi possível salvar a leitura. Tente novamente.");
    },
  });

  // Verificação de conta vencida: só dispara a mutation direto se a data de
  // vencimento calculada (contrato + período) ainda não passou. Se já
  // passou, abre o AlertDialog e espera a decisão do usuário em vez de
  // gravar de imediato.
  const handleConfirmarClick = () => {
    if (!contratoSelecionado || !campos.periodoInicio) {
      confirmarMutation.mutate({});
      return;
    }

    const mesReferencia = primeiroDiaDoMes(campos.periodoInicio);
    const dataVencimento = dataVencimentoDoMes(contratoSelecionado.dia_vencimento, mesReferencia);
    const hojeISO = new Date().toISOString().slice(0, 10);

    if (dataVencimento < hojeISO) {
      setContaVencidaPendente({ dataVencimento });
      return;
    }

    confirmarMutation.mutate({});
  };

  const contratosFiltrados = contratosAtivos.filter((c) => {
    const termo = buscaManual.trim().toLowerCase();
    if (!termo) return true;
    return (
      c.imovel_identificacao.toLowerCase().includes(termo) ||
      c.imovel_endereco.toLowerCase().includes(termo)
    );
  });

  const candidatosOrdenados = [...candidatos].sort((a, b) => b.confianca - a.confianca);

  return (
    <>
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <ScanSearch className="h-5 w-5 text-primary" />
          Lançar Conta de Água por Comprovante
        </CardTitle>
        <CardDescription>
          Envie o PDF da conta, a IA lê o documento e sugere o contrato correspondente — a
          confirmação final é sempre sua, com o comprovante ao lado.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {step === 1 && (
          <div className="space-y-4">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                handleFile(e.dataTransfer.files?.[0] ?? null);
              }}
              className={cn(
                "border-2 border-dashed rounded-xl p-10 text-center transition-colors",
                dragOver ? "border-primary bg-primary/5" : "border-border bg-muted/20",
              )}
            >
              <CloudUpload className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
              <p className="font-medium">Arraste a conta de água aqui</p>
              <p className="text-sm text-muted-foreground mb-4">Apenas 1 arquivo PDF por vez</p>
              <label>
                <input
                  type="file"
                  accept="application/pdf"
                  className="hidden"
                  onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
                />
                <span className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium cursor-pointer hover:opacity-90">
                  <Upload className="h-4 w-4" /> Selecionar PDF
                </span>
              </label>
              {file && (
                <div className="mt-4 inline-flex items-center gap-2 text-sm bg-background border rounded-md px-3 py-1.5">
                  <FileText className="h-4 w-4" /> {file.name}
                </div>
              )}
            </div>
            <div className="flex justify-end">
              <Button onClick={processarArquivo} disabled={loading}>
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Lendo documento com IA...
                  </>
                ) : (
                  "Processar conta"
                )}
              </Button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="grid lg:grid-cols-2 gap-6 items-start">
            {/* Lado esquerdo — documento original, sempre visível durante a conferência */}
            <div className="lg:sticky lg:top-4 h-[70vh] rounded-lg border overflow-hidden bg-muted/20">
              {previewUrl && <iframe src={previewUrl} title="Conta de água" className="w-full h-full" />}
            </div>

            {/* Lado direito — dados extraídos (editáveis) + escolha do contrato */}
            <div className="space-y-5">
              <div className="rounded-lg bg-[var(--info-bg)] border border-[var(--info-border)] p-3 flex gap-2 text-sm text-[var(--info-strong)]">
                <Info className="h-4 w-4 mt-0.5 shrink-0" />
                <span>Confira cada campo ao lado do PDF antes de confirmar o lançamento.</span>
              </div>

              <div className="grid sm:grid-cols-2 gap-4">
                <FieldAgua label="Condomínio / Edifício">
                  <Input
                    value={campos.condominio}
                    onChange={(e) => setCampos((p) => ({ ...p, condominio: e.target.value }))}
                  />
                </FieldAgua>
                <FieldAgua label="Apartamento">
                  <Input
                    value={campos.apartamento}
                    onChange={(e) => setCampos((p) => ({ ...p, apartamento: e.target.value }))}
                  />
                </FieldAgua>
                <FieldAgua label="Bloco">
                  <Input
                    value={campos.bloco}
                    onChange={(e) => setCampos((p) => ({ ...p, bloco: e.target.value }))}
                  />
                </FieldAgua>
                <FieldAgua label="Valor total (R$)">
                  <Input
                    type="number"
                    step="0.01"
                    value={campos.valorTotal}
                    onChange={(e) => setCampos((p) => ({ ...p, valorTotal: Number(e.target.value) }))}
                  />
                </FieldAgua>
                <FieldAgua label="Período — início">
                  <Input
                    type="date"
                    value={campos.periodoInicio}
                    onChange={(e) => setCampos((p) => ({ ...p, periodoInicio: e.target.value }))}
                  />
                </FieldAgua>
                <FieldAgua label="Período — fim">
                  <Input
                    type="date"
                    value={campos.periodoFim}
                    onChange={(e) => setCampos((p) => ({ ...p, periodoFim: e.target.value }))}
                  />
                </FieldAgua>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-medium">Contrato correspondente</Label>
                  {!modoBuscaManual && (
                    <button
                      type="button"
                      onClick={() => setModoBuscaManual(true)}
                      className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2"
                    >
                      Escolher manualmente
                    </button>
                  )}
                </div>

                {!modoBuscaManual && cenario === "confiavel" && candidatosOrdenados[0] && (
                  <CandidatoCard
                    candidato={candidatosOrdenados[0]}
                    selecionado={contratoSelecionadoId === candidatosOrdenados[0].contractId}
                    onSelecionar={() => setContratoSelecionadoId(candidatosOrdenados[0].contractId)}
                  />
                )}

                {!modoBuscaManual && cenario === "ambiguidade" && (
                  <div className="grid sm:grid-cols-2 gap-3">
                    {candidatosOrdenados.map((c) => (
                      <CandidatoCard
                        key={c.contractId}
                        candidato={c}
                        selecionado={contratoSelecionadoId === c.contractId}
                        onSelecionar={() => setContratoSelecionadoId(c.contractId)}
                      />
                    ))}
                  </div>
                )}

                {(modoBuscaManual || cenario === "lista_completa") && (
                  <div className="space-y-2">
                    {cenario === "lista_completa" && (
                      <div className="rounded-lg bg-[var(--warning-bg)] border border-[var(--warning-border)] p-3 flex gap-2 text-sm text-[var(--warning-fg)]">
                        <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                        <span>
                          Não encontramos uma correspondência confiável. Localize o contrato manualmente.
                        </span>
                      </div>
                    )}
                    <div className="relative">
                      <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        placeholder="Buscar por identificação ou endereço do imóvel"
                        value={buscaManual}
                        onChange={(e) => setBuscaManual(e.target.value)}
                        className="pl-9"
                      />
                    </div>
                    <div className="max-h-56 overflow-y-auto rounded-lg border divide-y">
                      {contratosFiltrados.length === 0 && (
                        <div className="p-3 text-sm text-muted-foreground">Nenhum contrato encontrado</div>
                      )}
                      {contratosFiltrados.map((c) => (
                        <button
                          key={c.id}
                          type="button"
                          onClick={() => setContratoSelecionadoId(c.id)}
                          className={cn(
                            "w-full text-left px-3 py-2.5 text-sm hover:bg-muted/50 transition-colors",
                            contratoSelecionadoId === c.id && "bg-primary/5",
                          )}
                        >
                          <div className="font-medium flex items-center gap-2">
                            {c.imovel_identificacao}
                            {contratoSelecionadoId === c.id && (
                              <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
                            )}
                          </div>
                          <div className="text-xs text-muted-foreground">{c.imovel_endereco}</div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="flex justify-between pt-2">
                <Button variant="outline" onClick={resetar} disabled={confirmarMutation.isPending}>
                  Cancelar
                </Button>
                <Button
                  onClick={handleConfirmarClick}
                  disabled={!contratoSelecionadoId || confirmarMutation.isPending}
                >
                  {confirmarMutation.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Salvando...
                    </>
                  ) : (
                    "Confirmar Lançamento"
                  )}
                </Button>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>

    <AlertDialog
      open={!!contaVencidaPendente}
      onOpenChange={(open) => {
        if (!open) setContaVencidaPendente(null);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Conta já vencida</AlertDialogTitle>
          <AlertDialogDescription>
            A data de vencimento desta cobrança ({formatarDataBR(contaVencidaPendente?.dataVencimento)}
            ) já passou. Tem certeza que deseja lançar essa conta mesmo assim?
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            onClick={() => {
              setContaVencidaPendente(null);
              resetar();
            }}
          >
            Não, cancelar
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              setContaVencidaPendente(null);
              confirmarMutation.mutate({ statusForcado: "atrasado" });
            }}
          >
            Sim, lançar mesmo assim
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    </>
  );
}

function CandidatoCard({
  candidato,
  selecionado,
  onSelecionar,
}: {
  candidato: CandidatoValido;
  selecionado: boolean;
  onSelecionar: () => void;
}) {
  // A pontuação de confiança nunca é exibida ao usuário — ela só orienta,
  // por trás dos panos, qual cenário de conferência aparece na tela
  // (ver classificarCenario). Aqui, o badge é sempre qualitativo.
  return (
    <button
      type="button"
      onClick={onSelecionar}
      className={cn(
        "text-left rounded-lg border-2 p-4 transition-colors w-full",
        selecionado ? "border-primary bg-primary/5" : "border-border hover:border-primary/40",
      )}
    >
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="font-medium">{candidato.imovel_identificacao}</span>
        <Badge variant={candidato.confianca >= CONFIANCA_MINIMA ? "default" : "secondary"}>
          Sugestão da IA
        </Badge>
      </div>
      <div className="text-xs text-muted-foreground mb-2">{candidato.imovel_endereco}</div>
      <div className="text-xs text-muted-foreground italic">{candidato.justificativa}</div>
      {selecionado && (
        <div className="mt-2 flex items-center gap-1 text-xs text-primary font-medium">
          <CheckCircle2 className="h-3.5 w-3.5" /> Selecionado
        </div>
      )}
    </button>
  );
}

function FieldAgua({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-sm">{label}</Label>
      {children}
    </div>
  );
}