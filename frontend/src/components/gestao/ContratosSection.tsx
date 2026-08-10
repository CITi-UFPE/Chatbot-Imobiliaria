import { useState } from "react";
import { toast } from "sonner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  CloudUpload,
  FileText,
  History,
  Info,
  ListFilter,
  Loader2,
  Sparkles,
  Upload,
} from "lucide-react";
import { PageHeader } from "./PageHeader";
import { StatTile } from "./StatTile";
import { Avatar } from "./Avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
import type { ContractRow, GarantiaTipo, TipoLocatario } from "@/lib/database.types";

const CONTRATOS_QUERY_KEY = ["contracts"] as const;

// Tipo de renovação (Migration 014) — escolhido manualmente pela gestora
// aqui no Passo 3, NÃO é inferido pela IA na extração. Decide o
// comportamento do cron do A4 no vencimento — ver
// app/agents/a4_gestao_contratual/fluxo.py::processar_finalizacao_contrato.
type TipoRenovacao =
  | "novo_contrato"
  | "requer_aditivo"
  | "automatica"
  | "indeterminado_por_lei"
  | "nao_identificado";

// "Acionáveis" = tipos que ficam pendentes de decisão da gestora se
// ninguém resolver até data_termino (card com ação em RenovacaoSection.tsx).
// novo_contrato e indeterminado_por_lei nunca ficam pendentes — o primeiro
// só é informativo, o segundo transiciona sozinho por força de lei.
const TIPOS_RENOVACAO_ACIONAVEIS: readonly TipoRenovacao[] = [
  "requer_aditivo",
  "automatica",
  "nao_identificado",
];

const OPCOES_TIPO_RENOVACAO: { value: TipoRenovacao; label: string; descricao: string }[] = [
  {
    value: "novo_contrato",
    label: "Novo contrato",
    descricao:
      "Ao vencer, a continuidade é feita cadastrando um contrato novo — não um aditivo a este. Cobre também os casos em que não haverá continuidade.",
  },
  {
    value: "requer_aditivo",
    label: "Requer aditivo",
    descricao: "Só prorroga mediante assinatura de um Termo Aditivo formal a este contrato.",
  },
  {
    value: "automatica",
    label: "Renovação automática",
    descricao:
      "Tem cláusula de renovação automática; o resultado (nova data de vencimento ou prazo indefinido) é confirmado no momento certo.",
  },
  {
    value: "indeterminado_por_lei",
    label: "Prazo indeterminado por lei",
    descricao:
      "O contrato é omisso quanto à renovação; a prorrogação decorre exclusivamente da lei, sem decisão a tomar.",
  },
  {
    value: "nao_identificado",
    label: "Nenhuma das anteriores",
    descricao:
      'Nenhuma opção acima descreve bem este contrato. Tratado com o mesmo rigor de "Requer aditivo".',
  },
];

function isDataPassada(dataStr: string): boolean {
  if (!dataStr) return false;
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const data = new Date(`${dataStr}T00:00:00`);
  return data < hoje;
}

// Formato retornado pelo agente de extração (app/tools/contract_extraction.py,
// modelo ExtracaoContratoResult em app/models/contract.py). Espelha o schema
// SQL 1:1 — se o backend mudar de nome um campo, este tipo também precisa mudar.
//
// Nota: o formulário abaixo (Passo 3) só expõe pra edição manual os campos
// mais prováveis de precisar de correção humana. Os demais campos NOT NULL
// do banco (multa_infracao_*, aviso_previo_*, garantia_tipo) vêm preenchidos
// pela extração e são enviados como estão — sem tela própria ainda. Se a
// extração falhar em algum desses, o insert abaixo vai falhar com o erro do
// Postgres (mais seguro do que inventar um valor default).
//
// tipo_renovacao e prazo_indeterminado NÃO fazem parte deste tipo: a IA não
// classifica renovação (Migration 014) — são estado próprio do wizard,
// definido pela gestora, e só entram no payload no momento do insert.
interface ContratoExtraido {
  imovel_identificacao: string;
  imovel_endereco: string;
  tipo_locatario: TipoLocatario;
  inquilino_nome: string;
  inquilino_cpf_cnpj: string;
  locatario_endereco: string | null;
  responsavel_contato_nome: string | null;
  fiador_nome: string | null;
  fiador_cpf: string | null;
  fiador_endereco: string | null;
  garantia_tipo: GarantiaTipo;
  garantia_valor: number | null;
  valor_aluguel: number;
  dia_vencimento: number;
  data_inicio: string; // YYYY-MM-DD
  data_termino: string; // YYYY-MM-DD
  indice_reajuste: "igpm" | "livre_negociacao" | null;
  data_aniversario_reajuste: string | null;
  multa_infracao_tipo: "meses_aluguel" | "percentual_valor_anual";
  multa_infracao_valor: number;
  multa_moratoria_percentual: number | null;
  juros_moratorio_mensal: number;
  aviso_previo_dias: number;
  aviso_previo_a_partir_mes: number;
  banco_agencia: string | null;
  banco_conta: string | null;
  pix_chave: string | null;
  observacoes: string | null;
}

interface ClausulaExtraida {
  numero_clausula: string;
  titulo_clausula: string;
  texto_clausula: string;
  categoria: string;
}

interface ExtracaoContratoResult {
  contrato: ContratoExtraido;
  clausulas: ClausulaExtraida[];
}

async function fetchContracts(): Promise<ContractRow[]> {
  const { data, error } = await supabase
    .from("contracts")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) throw error;
  return data ?? [];
}

export function ContratosSection() {
  const queryClient = useQueryClient();
  const [toDeactivate, setToDeactivate] = useState<ContractRow | null>(null);
  const [toReactivate, setToReactivate] = useState<ContractRow | null>(null);
  const [apenasAtivos, setApenasAtivos] = useState(false);

  const { data: imoveis = [], isLoading, isError } = useQuery({
    queryKey: CONTRATOS_QUERY_KEY,
    queryFn: fetchContracts,
  });

  const imoveisFiltrados = apenasAtivos
    ? imoveis.filter((i) => i.status === "ativo")
    : imoveis;

  const deactivateMutation = useMutation({
    mutationFn: async (contractId: string) => {
      const { error } = await supabase
        .from("contracts")
        .update({ status: "inativo" })
        .eq("id", contractId);
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success("Contrato desativado com sucesso");
      setToDeactivate(null);
      queryClient.invalidateQueries({ queryKey: CONTRATOS_QUERY_KEY });
    },
    onError: (error) => {
      console.error("Erro ao desativar contrato:", error);
      toast.error("Não foi possível desativar o contrato. Tente novamente.");
    },
  });

  const reactivateMutation = useMutation({
    mutationFn: async (contractId: string) => {
      const { error } = await supabase
        .from("contracts")
        .update({ status: "ativo" })
        .eq("id", contractId);
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success("Contrato reativado com sucesso");
      setToReactivate(null);
      queryClient.invalidateQueries({ queryKey: CONTRATOS_QUERY_KEY });
    },
    onError: (error) => {
      console.error("Erro ao reativar contrato:", error);
      toast.error("Não foi possível reativar o contrato. Tente novamente.");
    },
  });

  return (
    <div className="space-y-10">
      <div>
        <PageHeader
          title="Contratos"
          description={
            <>
              Gerencie imóveis cadastrados e faça o upload de novos contratos com extração
              automática por <span style={{ color: "var(--brand)" }} className="font-medium">IA</span>.
            </>
          }
        />

        <div className="grid gap-4 sm:grid-cols-3 mb-6">
          <StatTile
            tone="a"
            icon={<FileText className="h-5 w-5" />}
            label="Imóveis Cadastrados"
            value={imoveis.length}
            sublabel="no total"
          />
          <StatTile
            tone="d"
            icon={<CheckCircle2 className="h-5 w-5" />}
            label="Contratos Ativos"
            value={imoveis.filter((i) => i.status === "ativo").length}
            sublabel="em vigência"
          />
          <StatTile
            tone="c"
            icon={<Clock className="h-5 w-5" />}
            label="Pendentes"
            value={imoveis.filter((i) => i.status === "pendente_confirmacao").length}
            sublabel="aguardando confirmação"
          />
        </div>

        <div className="flex items-center justify-between mb-4">
          <p className="text-sm text-muted-foreground">
            {apenasAtivos
              ? "Mostrando apenas contratos ativos."
              : "Mostrando todos os contratos."}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setApenasAtivos((prev) => !prev)}
          >
            {apenasAtivos ? (
              <>
                <History className="h-4 w-4 mr-2" /> Ver todos
              </>
            ) : (
              <>
                <ListFilter className="h-4 w-4 mr-2" /> Ver só ativos
              </>
            )}
          </Button>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Imóveis Cadastrados</CardTitle>
            <CardDescription>
              {isLoading ? "Carregando..." : `${imoveisFiltrados.length} imóveis no total`}
            </CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            {isError && (
              <p className="px-6 py-4 text-sm text-destructive">
                Não foi possível carregar os contratos. Verifique sua sessão e tente novamente.
              </p>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-muted-foreground">
                  <tr>
                    <th className="text-left font-medium px-6 py-3">Imóvel</th>
                    <th className="text-left font-medium px-6 py-3">Inquilino</th>
                    <th className="text-left font-medium px-6 py-3">Status</th>
                    <th className="text-right font-medium px-6 py-3">Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {imoveisFiltrados.map((im) => (
                    <tr key={im.id} className="border-t hover:bg-muted/30 transition-colors">
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <Avatar name={im.inquilino_nome} size={34} />
                          <div>
                            <div className="font-medium">{im.inquilino_nome}</div>
                            <div className="text-xs text-muted-foreground">{im.imovel_endereco}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        {im.status === "ativo" ? (
                          <Badge className="border-[var(--success-border)] bg-[var(--success-bg)] text-[var(--success-fg)] hover:bg-[var(--success-bg)]">
                            Ativo
                          </Badge>
                        ) : im.status === "pendente_confirmacao" ? (
                          <Badge className="border-[var(--warning-border)] bg-[var(--warning-bg)] text-[var(--warning-fg)] hover:bg-[var(--warning-bg)]">
                            Pendente de confirmação
                          </Badge>
                        ) : (
                          <Badge variant="secondary">Inativo</Badge>
                        )}
                      </td>
                      <td className="px-6 py-4 text-right">
                        {im.status === "ativo" ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setToDeactivate(im)}
                          >
                            Desativar Contrato
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setToReactivate(im)}
                          >
                            Reativar Contrato
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>

      <UploadWizard
        existingActiveAddresses={imoveis
          .filter((i) => i.status === "ativo")
          .map((i) => i.imovel_endereco)}
      />

      <AlertDialog open={!!toDeactivate} onOpenChange={(o) => !o && setToDeactivate(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Desativar contrato?</AlertDialogTitle>
            <AlertDialogDescription>
              O contrato de <strong>{toDeactivate?.inquilino_nome}</strong> em{" "}
              <strong>{toDeactivate?.imovel_endereco}</strong> será marcado como inativo.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deactivateMutation.isPending}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => toDeactivate && deactivateMutation.mutate(toDeactivate.id)}
              disabled={deactivateMutation.isPending}
            >
              {deactivateMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Desativando...
                </>
              ) : (
                "Sim, desativar"
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={!!toReactivate} onOpenChange={(o) => !o && setToReactivate(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reativar contrato?</AlertDialogTitle>
            <AlertDialogDescription>
              O contrato de <strong>{toReactivate?.inquilino_nome}</strong> em{" "}
              <strong>{toReactivate?.imovel_endereco}</strong> será marcado como ativo.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={reactivateMutation.isPending}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => toReactivate && reactivateMutation.mutate(toReactivate.id)}
              disabled={reactivateMutation.isPending}
            >
              {reactivateMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Reativando...
                </>
              ) : (
                "Sim, reativar"
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

/* ---------- Upload Wizard ---------- */

type Step = 1 | 2 | 3;

function UploadWizard({
  existingActiveAddresses,
}: {
  existingActiveAddresses: string[];
}) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState<Step>(1);
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);

  // Dados extraídos pelo agente de IA no Passo 1 -> 2. null até a extração
  // acontecer; ficam editáveis no Passo 3 antes de salvar.
  const [dados, setDados] = useState<ContratoExtraido | null>(null);
  const [clausulas, setClausulas] = useState<ClausulaExtraida[]>([]);
  const [whatsapp, setWhatsapp] = useState("");

  // Tipo de renovação (Migration 014) — seletor manual, não vem da
  // extração. "novo_contrato" é o default por ser o caso mais comum.
  const [tipoRenovacao, setTipoRenovacao] = useState<TipoRenovacao>("novo_contrato");
  // Resolução exigida no próprio cadastro quando o contrato já está
  // vencido e o tipo é "acionável" (requer_aditivo/automatica/nao_identificado)
  // — não existe opção de adiar essa decisão pra depois.
  const [resolucaoModo, setResolucaoModo] = useState<"nova_data" | "indefinido">("nova_data");
  const [resolucaoNovaData, setResolucaoNovaData] = useState("");

  const duplicado =
    !!dados &&
    existingActiveAddresses.some((a) => a.toLowerCase() === dados.imovel_endereco.toLowerCase());

  const vencido = !!dados && isDataPassada(dados.data_termino);
  const acionavel = TIPOS_RENOVACAO_ACIONAVEIS.includes(tipoRenovacao);
  const bloqueadoPorVencimento = tipoRenovacao === "novo_contrato" && vencido;
  const resolucaoIncompleta =
    vencido && acionavel && resolucaoModo === "nova_data" && !resolucaoNovaData;

  const handleFile = (f: File | null) => {
    if (!f) return;
    setFile(f);
  };

  // ==========================================================
  // 🔌 PONTO DE INTEGRAÇÃO: chamada ao agente de extração (IA)
  // ==========================================================
  // Envia o PDF pro backend FastAPI (app/api/routers/contracts.py), que
  // chama app/tools/contract_extraction.py (Claude API) e devolve o JSON
  // no formato de ExtracaoContratoResult. O front só repassa, já tipado.
  const extrairDadosDoContrato = async (arquivo: File): Promise<ExtracaoContratoResult> => {
    const formData = new FormData();
    formData.append("arquivo", arquivo);

    const apiUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5 * 60 * 1000);
    const response = await fetch(`${apiUrl}/contracts/extrair`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    }).finally(() => clearTimeout(timeout));

    if (!response.ok) {
      const erro = await response.json().catch(() => null);
      throw new Error(erro?.detail ?? "Falha ao extrair dados do contrato.");
    }

    return response.json();
  };

  const goToStep2 = async () => {
    if (!file) {
      toast.error("Selecione um arquivo de contrato primeiro");
      return;
    }

    setLoading(true);
    try {
      const resultado = await extrairDadosDoContrato(file);
      setDados(resultado.contrato);
      setClausulas(resultado.clausulas);
      setStep(2);
    } catch (error) {
      console.error("Erro ao extrair dados do contrato:", error);
      toast.error("Não foi possível processar o contrato. Tente novamente.");
    } finally {
      setLoading(false);
    }
  };

  const submitMutation = useMutation({
    mutationFn: async () => {
      if (!dados) throw new Error("Nenhum dado extraído para salvar");
      if (!whatsapp.trim()) throw new Error("WhatsApp é obrigatório");

      const dadosVencido = isDataPassada(dados.data_termino);

      if (tipoRenovacao === "novo_contrato" && dadosVencido) {
        throw new Error(
          'Contrato do tipo "Novo contrato" não pode ser cadastrado já vencido — corrija a data ou escolha outro tipo de renovação.',
        );
      }

      // data_termino/prazo_indeterminado finais a gravar: por padrão são os
      // extraídos do PDF; só mudam se o contrato já está vencido e a
      // renovação precisa ser resolvida (ou já é resolvida por lei) no
      // próprio cadastro.
      let dataTerminoFinal = dados.data_termino;
      let prazoIndeterminadoFinal = false;

      if (dadosVencido && tipoRenovacao === "indeterminado_por_lei") {
        // Sem decisão a tomar: a lei já teria produzido prazo indeterminado
        // nesse meio-tempo, então o contrato entra direto nesse estado.
        prazoIndeterminadoFinal = true;
      } else if (dadosVencido && TIPOS_RENOVACAO_ACIONAVEIS.includes(tipoRenovacao)) {
        if (resolucaoModo === "indefinido") {
          prazoIndeterminadoFinal = true;
        } else {
          if (!resolucaoNovaData) {
            throw new Error("Defina a nova data de vencimento antes de salvar.");
          }
          dataTerminoFinal = resolucaoNovaData;
        }
      }

      // status entra sempre como pendente_confirmacao — dado extraído por IA
      // nunca vira contrato "ativo" direto, precisa de revisão humana
      // (mesmo raciocínio da migration: mais seguro nascer travado).
      const { data: contractRow, error: contractError } = await supabase
        .from("contracts")
        .insert({
          ...dados,
          data_termino: dataTerminoFinal,
          tipo_renovacao: tipoRenovacao,
          prazo_indeterminado: prazoIndeterminadoFinal,
          telefone_whatsapp: whatsapp,
          status: "pendente_confirmacao",
        })
        .select()
        .single();

      if (contractError) throw contractError;

      if (clausulas.length > 0) {
        const { error: clausulasError } = await supabase.from("contract_clauses").insert(
          clausulas.map((c) => ({
            contract_id: contractRow.id,
            numero_clausula: c.numero_clausula,
            titulo_clausula: c.titulo_clausula,
            texto_clausula: c.texto_clausula,
            categoria: c.categoria,
          })),
        );
        // Se as cláusulas falharem, o contrato já foi criado — melhor avisar
        // e deixar staff revisar manualmente do que reverter silenciosamente.
        if (clausulasError) {
          console.error("Contrato criado, mas cláusulas falharam:", clausulasError);
          toast.error(
            "Contrato salvo, mas as cláusulas não foram gravadas. Revise manualmente.",
          );
        }
      }

      return contractRow;
    },
    onSuccess: () => {
      toast.success("Contrato salvo como pendente de confirmação!");
      queryClient.invalidateQueries({ queryKey: CONTRATOS_QUERY_KEY });
      setStep(1);
      setFile(null);
      setDados(null);
      setClausulas([]);
      setWhatsapp("");
      setTipoRenovacao("novo_contrato");
      setResolucaoModo("nova_data");
      setResolucaoNovaData("");
    },
    onError: (error: Error) => {
      console.error("Erro ao salvar contrato:", error);
      toast.error(error.message || "Não foi possível salvar o contrato. Tente novamente.");
    },
  });

  const updateDados = (patch: Partial<ContratoExtraido>) =>
    setDados((prev) => (prev ? { ...prev, ...patch } : prev));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-primary" />
          Novo Contrato — Upload com IA
        </CardTitle>
        <CardDescription>Fluxo em 3 passos com extração automática via Claude API</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <Stepper step={step} />

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
              <p className="font-medium">Arraste o contrato aqui</p>
              <p className="text-sm text-muted-foreground mb-4">
                Arquivos aceitos: PDF, JPG, PNG (até 10MB)
              </p>
              <label>
                <input
                  type="file"
                  accept=".pdf,image/*"
                  className="hidden"
                  onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
                />
                <span className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium cursor-pointer hover:opacity-90">
                  <Upload className="h-4 w-4" /> Selecionar arquivo
                </span>
              </label>
              {file && (
                <div className="mt-4 inline-flex items-center gap-2 text-sm bg-background border rounded-md px-3 py-1.5">
                  <FileText className="h-4 w-4" /> {file.name}
                </div>
              )}
            </div>
            <div className="flex justify-end">
              <Button onClick={goToStep2} disabled={loading}>
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Processando com IA...
                  </>
                ) : (
                  "Avançar"
                )}
              </Button>
            </div>
          </div>
        )}

        {step === 2 && dados && (
          <div className="space-y-4">
            <div className="rounded-lg bg-[var(--success-bg)] border border-[var(--success-border)] p-4 flex gap-3">
              <CheckCircle2 className="h-5 w-5 text-[var(--success-accent)] shrink-0 mt-0.5" />
              <div className="text-sm">
                <div className="font-medium text-[var(--success-strong)]">Extração concluída pela Claude API</div>
                <div className="text-[var(--success-fg)]">
                  {clausulas.length} cláusulas identificadas. Revise no próximo passo.
                </div>
              </div>
            </div>

            {duplicado && (
              <div className="rounded-lg bg-[var(--warning-bg)] border-2 border-[var(--warning-accent)] p-4 flex gap-3 animate-pulse">
                <AlertCircle className="h-5 w-5 text-[var(--warning-accent)] shrink-0 mt-0.5" />
                <div className="text-sm">
                  <div className="font-bold text-[var(--warning-strong)]">⚠ Contrato duplicado detectado</div>
                  <div className="text-[var(--warning-fg)]">
                    Já existe um contrato <strong>ativo</strong> para o imóvel{" "}
                    <strong>{dados.imovel_endereco}</strong>. Verifique antes de prosseguir.
                  </div>
                </div>
              </div>
            )}

            <dl className="grid sm:grid-cols-2 gap-4 text-sm bg-muted/30 rounded-lg p-4">
              <ExtractRow label="Imóvel" value={dados.imovel_endereco} />
              <ExtractRow label="Inquilino" value={dados.inquilino_nome} />
              <ExtractRow label="Valor" value={`R$ ${dados.valor_aluguel}`} />
              <ExtractRow label="Vencimento (término)" value={dados.data_termino} />
              <ExtractRow label="Fiador" value={dados.fiador_nome ?? "—"} />
              <ExtractRow label="Cláusulas" value={`${clausulas.length} detectadas`} />
            </dl>

            <div className="flex justify-between">
              <Button variant="outline" onClick={() => setStep(1)}>
                Voltar
              </Button>
              <Button onClick={() => setStep(3)}>Revisar e confirmar</Button>
            </div>
          </div>
        )}

        {step === 3 && dados && (
          <div className="space-y-5">
            <div className="grid md:grid-cols-2 gap-4">
              <Field label="Imóvel">
                <Input
                  value={dados.imovel_endereco}
                  onChange={(e) => updateDados({ imovel_endereco: e.target.value })}
                />
              </Field>
              <Field label="Inquilino">
                <Input
                  value={dados.inquilino_nome}
                  onChange={(e) => updateDados({ inquilino_nome: e.target.value })}
                />
              </Field>
              <Field label="Valor do Aluguel (R$)">
                <Input
                  type="number"
                  value={dados.valor_aluguel}
                  onChange={(e) => updateDados({ valor_aluguel: Number(e.target.value) })}
                />
              </Field>
              <Field label="Data de Término">
                <Input
                  type="date"
                  value={dados.data_termino}
                  onChange={(e) => updateDados({ data_termino: e.target.value })}
                />
              </Field>
              <Field label="Fiador">
                <Input
                  value={dados.fiador_nome ?? ""}
                  onChange={(e) => updateDados({ fiador_nome: e.target.value || null })}
                />
              </Field>
              <Field label="WhatsApp do inquilino/responsável *">
                <Input
                  placeholder="+55 81 99999-9999"
                  value={whatsapp}
                  onChange={(e) => setWhatsapp(e.target.value)}
                />
              </Field>
            </div>

            {/* Tipo de renovação (Migration 014) — seletor manual, decide o
                comportamento do contrato no vencimento (ver
                app/agents/a4_gestao_contratual/fluxo.py). */}
            <div className="rounded-lg border p-4 space-y-4">
              <Field label="Tipo de renovação">
                <Select
                  value={tipoRenovacao}
                  onValueChange={(v) => setTipoRenovacao(v as TipoRenovacao)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {OPCOES_TIPO_RENOVACAO.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <p className="text-xs text-muted-foreground">
                {OPCOES_TIPO_RENOVACAO.find((o) => o.value === tipoRenovacao)?.descricao}
              </p>

              {bloqueadoPorVencimento && (
                <div className="rounded-lg bg-destructive/10 border border-destructive/30 p-3 flex gap-2 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                  <p>
                    Este contrato está vencido (término em {dados.data_termino}). Contratos do
                    tipo "Novo contrato" não podem ser cadastrados vencidos — corrija a data ou
                    escolha outro tipo de renovação.
                  </p>
                </div>
              )}

              {vencido && acionavel && (
                <div className="rounded-lg bg-[var(--warning-bg)] border border-[var(--warning-border)] p-3 space-y-3">
                  <p className="text-sm text-[var(--warning-fg)] font-medium">
                    Este contrato está vencido — defina a renovação antes de salvar.
                  </p>
                  <Field label="Renovação">
                    <Select
                      value={resolucaoModo}
                      onValueChange={(v) => setResolucaoModo(v as typeof resolucaoModo)}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="nova_data">Nova data de vencimento</SelectItem>
                        <SelectItem value="indefinido">Prazo indefinido</SelectItem>
                      </SelectContent>
                    </Select>
                  </Field>
                  {resolucaoModo === "nova_data" && (
                    <Field label="Nova data de vencimento">
                      <Input
                        type="date"
                        value={resolucaoNovaData}
                        onChange={(e) => setResolucaoNovaData(e.target.value)}
                      />
                    </Field>
                  )}
                </div>
              )}

              {vencido && tipoRenovacao === "indeterminado_por_lei" && (
                <div className="flex items-start gap-2 text-sm text-muted-foreground bg-muted/30 rounded-lg p-3">
                  <Info className="h-4 w-4 mt-0.5 shrink-0" />
                  <p>
                    Este contrato está vencido e é omisso quanto à renovação — será cadastrado
                    diretamente como prazo indeterminado, sem necessidade de decisão.
                  </p>
                </div>
              )}
            </div>

            {/* Campos abaixo são obrigatórios no banco (NOT NULL) mas raramente
                precisam de correção manual — por isso ficam num bloco separado,
                só leitura por padrão, editáveis se algo vier errado da extração. */}
            <details className="rounded-lg border p-4">
              <summary className="cursor-pointer text-sm font-medium">
                Outros campos obrigatórios (garantia, multa, aviso prévio)
              </summary>
              <div className="grid md:grid-cols-2 gap-4 mt-4">
                <Field label="Tipo de garantia">
                  <Select
                    value={dados.garantia_tipo}
                    onValueChange={(v) => updateDados({ garantia_tipo: v as GarantiaTipo })}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="fiador">Fiador</SelectItem>
                      <SelectItem value="caucao">Caução</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Multa por infração (nº de aluguéis)">
                  <Input
                    type="number"
                    value={dados.multa_infracao_valor}
                    onChange={(e) => updateDados({ multa_infracao_valor: Number(e.target.value) })}
                  />
                </Field>
                <Field label="Aviso prévio (dias)">
                  <Input
                    type="number"
                    value={dados.aviso_previo_dias}
                    onChange={(e) => updateDados({ aviso_previo_dias: Number(e.target.value) })}
                  />
                </Field>
                <Field label="CPF/CNPJ do inquilino">
                  <Input
                    value={dados.inquilino_cpf_cnpj}
                    onChange={(e) => updateDados({ inquilino_cpf_cnpj: e.target.value })}
                  />
                </Field>
              </div>
            </details>

            <Field label="Cláusulas identificadas">
              <Textarea
                rows={4}
                readOnly
                value={clausulas.map((c) => `${c.numero_clausula} — ${c.titulo_clausula}`).join("\n")}
              />
            </Field>

            <div className="flex justify-between pt-2">
              <Button variant="outline" onClick={() => setStep(2)} disabled={submitMutation.isPending}>
                Voltar
              </Button>
              <Button
                onClick={() => submitMutation.mutate()}
                disabled={submitMutation.isPending || bloqueadoPorVencimento || resolucaoIncompleta}
              >
                {submitMutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Salvando...
                  </>
                ) : (
                  "Confirmar e Salvar Contrato"
                )}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Stepper({ step }: { step: Step }) {
  const steps = [
    { n: 1, label: "Upload do Contrato" },
    { n: 2, label: "Extração Claude API" },
    { n: 3, label: "Confirmação Manual" },
  ];
  return (
    <div className="flex items-center gap-2">
      {steps.map((s, i) => (
        <div key={s.n} className="flex items-center gap-2 flex-1 min-w-0">
          <div
            className={cn(
              "h-8 w-8 rounded-full flex items-center justify-center text-sm font-semibold shrink-0",
              step >= (s.n as Step)
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground",
            )}
          >
            {s.n}
          </div>
          <div
            className={cn(
              "text-sm font-medium truncate",
              step >= (s.n as Step) ? "text-foreground" : "text-muted-foreground",
            )}
          >
            {s.label}
          </div>
          {i < steps.length - 1 && (
            <div
              className={cn(
                "h-0.5 flex-1 rounded",
                step > (s.n as Step) ? "bg-primary" : "bg-border",
              )}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function ExtractRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase text-muted-foreground tracking-wide">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-sm">{label}</Label>
      {children}
    </div>
  );
}