import { useState } from "react";
import { toast } from "sonner";
import {
  AlertCircle,
  CheckCircle2,
  CloudUpload,
  FileText,
  Loader2,
  Sparkles,
  Upload,
} from "lucide-react";
import { PageHeader } from "./PageHeader";
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

interface Imovel {
  id: string;
  endereco: string;
  inquilino: string;
  ativo: boolean;
}

// Formato esperado de retorno do agente de extração (IA) ao ler o contrato.
// Ajuste os campos aqui se o seu agente retornar nomes diferentes.
interface DadosExtraidosContrato {
  endereco: string;
  inquilino: string;
  valor: string;
  vencimento: string; // formato "YYYY-MM-DD"
  fiador: string;
  clausulas: string;
}

const imoveisIniciais: Imovel[] = [
  { id: "1", endereco: "Rua das Palmeiras, 245 — Apto 302", inquilino: "Ana Beatriz Souza", ativo: true },
  { id: "2", endereco: "Av. Brasil, 1500 — Sala 8", inquilino: "Construtora Marca Ltda.", ativo: true },
  { id: "3", endereco: "Rua Antônio Carlos, 89", inquilino: "Rafael Mendes", ativo: true },
  { id: "4", endereco: "Alameda dos Ipês, 47", inquilino: "Marina Oliveira", ativo: false },
  { id: "5", endereco: "Rua Sete de Setembro, 1010", inquilino: "João Pedro Almeida", ativo: true },
];

export function ContratosSection() {
  const [imoveis, setImoveis] = useState(imoveisIniciais);
  const [toDeactivate, setToDeactivate] = useState<Imovel | null>(null);
  const [deactivating, setDeactivating] = useState(false);

  const deactivate = async () => {
    if (!toDeactivate) return;

    setDeactivating(true);
    try {
      // ==========================================================
      // 🔌 PONTO DE INTEGRAÇÃO: persistir a desativação no banco
      // ==========================================================
      // Chame aqui sua API/backend para marcar esse imóvel como
      // inativo na linha correspondente do banco de dados.
      //

      // ---- MOCK: remova quando plugar a chamada real acima ----
      await new Promise((resolve) => setTimeout(resolve, 400));
      // -----------------------------------------------------------

      setImoveis((prev) =>
        prev.map((i) => (i.id === toDeactivate.id ? { ...i, ativo: false } : i)),
      );
      toast.success("Contrato desativado com sucesso");
      setToDeactivate(null);
    } catch (error) {
      console.error("Erro ao desativar contrato:", error);
      toast.error("Não foi possível desativar o contrato. Tente novamente.");
    } finally {
      setDeactivating(false);
    }
  };

  return (
    <div className="space-y-10">
      <div>
        <PageHeader
          title="Contratos"
          description="Gerencie imóveis cadastrados e faça o upload de novos contratos com extração automática por IA."
        />

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Imóveis Cadastrados</CardTitle>
            <CardDescription>{imoveis.length} imóveis no total</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
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
                  {imoveis.map((im) => (
                    <tr key={im.id} className="border-t hover:bg-muted/30 transition-colors">
                      <td className="px-6 py-4 font-medium">{im.endereco}</td>
                      <td className="px-6 py-4 text-muted-foreground">{im.inquilino}</td>
                      <td className="px-6 py-4">
                        {im.ativo ? (
                          <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100 border-emerald-200">
                            Ativo
                          </Badge>
                        ) : (
                          <Badge variant="secondary">Inativo</Badge>
                        )}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={!im.ativo}
                          onClick={() => setToDeactivate(im)}
                        >
                          Desativar Contrato
                        </Button>
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
        existingActiveAddresses={imoveis.filter((i) => i.ativo).map((i) => i.endereco)}
        onCreate={(novo) => setImoveis((p) => [novo, ...p])}
      />

      <AlertDialog open={!!toDeactivate} onOpenChange={(o) => !o && setToDeactivate(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Desativar contrato?</AlertDialogTitle>
            <AlertDialogDescription>
              O contrato de <strong>{toDeactivate?.inquilino}</strong> em{" "}
              <strong>{toDeactivate?.endereco}</strong> será marcado como inativo.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deactivating}>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={deactivate} disabled={deactivating}>
              {deactivating ? (
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
    </div>
  );
}

/* ---------- Upload Wizard ---------- */

type Step = 1 | 2 | 3;

function UploadWizard({
  existingActiveAddresses,
  onCreate,
}: {
  existingActiveAddresses: string[];
  onCreate: (i: Imovel) => void;
}) {
  const [step, setStep] = useState<Step>(1);
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  // Extracted data (preenchido pelo agente de IA no Passo 1 -> 2)
  const [endereco, setEndereco] = useState("");
  const [inquilino, setInquilino] = useState("");
  const [valor, setValor] = useState("");
  const [vencimento, setVencimento] = useState("");
  const [fiador, setFiador] = useState("");
  const [clausulas, setClausulas] = useState("");
  const [camposExtraidosCount, setCamposExtraidosCount] = useState(0);

  const [whatsapp, setWhatsapp] = useState("");
  const [tipoLocatario, setTipoLocatario] = useState<"PF" | "PJ" | "">("");
  const [responsavelPJ, setResponsavelPJ] = useState("");

  const duplicado = existingActiveAddresses.some(
    (a) => a.toLowerCase() === endereco.toLowerCase(),
  );

  const handleFile = (f: File | null) => {
    if (!f) return;
    setFile(f);
  };

  // Chamada ao agente de extração. Hoje está mockada; troque o corpo
  // desta função pela chamada real (veja comentários abaixo).
  const extrairDadosDoContrato = async (arquivo: File): Promise<DadosExtraidosContrato> => {
    // ==========================================================
    // 🔌 PONTO DE INTEGRAÇÃO: chamada ao agente de extração (IA)
    // ==========================================================
    // Aqui é onde você deve chamar o agente responsável por ler o
    // arquivo (PDF/imagem do contrato) e extrair os dados estruturados.
    //
    // Fluxo sugerido:
    // 1) Envie o arquivo para o seu backend (multipart/form-data).
    // 2) No backend, converta o arquivo para base64 e chame a Claude
    //    API (endpoint /v1/messages), enviando o arquivo como um
    //    bloco "document" (PDF) ou "image", e peça uma resposta
    //    SOMENTE em JSON com os campos abaixo.
    // 3) O backend faz o parse do JSON e retorna para o front-end.
    // 4) Aqui no front, apenas repasse esse JSON já tipado.
    //
    // ==========================================================

    // ---- MOCK: remova este bloco quando plugar a chamada real acima ----
    await new Promise((resolve) => setTimeout(resolve, 1500));
    return {
      endereco: "Rua das Palmeiras, 245 — Apto 302",
      inquilino: "Ana Beatriz Souza",
      valor: "2500",
      vencimento: "2026-08-05",
      fiador: "Carlos Souza",
      clausulas:
        "Prazo de 30 meses. Reajuste anual pelo IGP-M. Multa de 3 aluguéis em caso de rescisão antecipada.",
    };
    // ---------------------------------------------------------------------
  };

  const goToStep2 = async () => {
    if (!file) {
      toast.error("Selecione um arquivo de contrato primeiro");
      return;
    }

    setLoading(true);
    try {
      const dados = await extrairDadosDoContrato(file);

      setEndereco(dados.endereco);
      setInquilino(dados.inquilino);
      setValor(dados.valor);
      setVencimento(dados.vencimento);
      setFiador(dados.fiador);
      setClausulas(dados.clausulas);
      setCamposExtraidosCount(Object.keys(dados).length);

      setStep(2);
    } catch (error) {
      console.error("Erro ao extrair dados do contrato:", error);
      toast.error("Não foi possível processar o contrato. Tente novamente.");
    } finally {
      setLoading(false);
    }
  };

  const submit = async () => {
    if (!whatsapp.trim()) return toast.error("WhatsApp é obrigatório");
    if (!tipoLocatario) return toast.error("Selecione o tipo de locatário");
    if (tipoLocatario === "PJ" && !responsavelPJ.trim())
      return toast.error("Informe o nome do responsável pelo contrato (PJ)");

    setSaving(true);
    try {
      // ==========================================================
      // 🔌 PONTO DE INTEGRAÇÃO: salvar o novo contrato no banco
      // ==========================================================
      // Chame aqui sua API/backend para persistir o novo imóvel/contrato,
      // incluindo os campos revisados manualmente (endereco, inquilino,
      // valor, vencimento, fiador, clausulas, whatsapp, tipoLocatario,
      // responsavelPJ) na linha correspondente do banco de dados.
      //
      // ==========================================================

      // ---- MOCK: remova quando plugar a chamada real acima ----
      await new Promise((resolve) => setTimeout(resolve, 400));
      onCreate({
        id: crypto.randomUUID(),
        endereco,
        inquilino,
        ativo: true,
      });
      // -----------------------------------------------------------

      toast.success("Contrato salvo e ativado com sucesso!");
      // reset
      setStep(1);
      setFile(null);
      setEndereco("");
      setInquilino("");
      setValor("");
      setVencimento("");
      setFiador("");
      setClausulas("");
      setCamposExtraidosCount(0);
      setWhatsapp("");
      setTipoLocatario("");
      setResponsavelPJ("");
    } catch (error) {
      console.error("Erro ao salvar contrato:", error);
      toast.error("Não foi possível salvar o contrato. Tente novamente.");
    } finally {
      setSaving(false);
    }
  };

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

        {step === 2 && (
          <div className="space-y-4">
            <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-4 flex gap-3">
              <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0 mt-0.5" />
              <div className="text-sm">
                <div className="font-medium text-emerald-800">Extração concluída pela Claude API</div>
                <div className="text-emerald-700">
                  Identificamos {camposExtraidosCount} campos no documento. Revise no próximo passo.
                </div>
              </div>
            </div>

            {duplicado && (
              <div className="rounded-lg bg-amber-50 border-2 border-amber-300 p-4 flex gap-3 animate-pulse">
                <AlertCircle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
                <div className="text-sm">
                  <div className="font-bold text-amber-900">⚠ Contrato duplicado detectado</div>
                  <div className="text-amber-800">
                    Já existe um contrato <strong>ativo</strong> para o imóvel{" "}
                    <strong>{endereco}</strong>. Verifique antes de prosseguir.
                  </div>
                </div>
              </div>
            )}

            <dl className="grid sm:grid-cols-2 gap-4 text-sm bg-muted/30 rounded-lg p-4">
              <ExtractRow label="Imóvel" value={endereco} />
              <ExtractRow label="Inquilino" value={inquilino} />
              <ExtractRow label="Valor" value={`R$ ${valor}`} />
              <ExtractRow label="Vencimento" value={vencimento} />
              <ExtractRow label="Fiador" value={fiador} />
              <ExtractRow label="Cláusulas" value="Detectadas" />
            </dl>

            <div className="flex justify-between">
              <Button variant="outline" onClick={() => setStep(1)}>
                Voltar
              </Button>
              <Button onClick={() => setStep(3)}>Revisar e confirmar</Button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-5">
            <div className="grid md:grid-cols-2 gap-4">
              <Field label="Imóvel">
                <Input value={endereco} onChange={(e) => setEndereco(e.target.value)} />
              </Field>
              <Field label="Inquilino">
                <Input value={inquilino} onChange={(e) => setInquilino(e.target.value)} />
              </Field>
              <Field label="Valor do Aluguel (R$)">
                <Input
                  type="number"
                  value={valor}
                  onChange={(e) => setValor(e.target.value)}
                />
              </Field>
              <Field label="Data de Vencimento">
                <Input
                  type="date"
                  value={vencimento}
                  onChange={(e) => setVencimento(e.target.value)}
                />
              </Field>
              <Field label="Fiador">
                <Input value={fiador} onChange={(e) => setFiador(e.target.value)} />
              </Field>
              <Field label="WhatsApp do inquilino/responsável *">
                <Input
                  placeholder="(11) 99999-9999"
                  value={whatsapp}
                  onChange={(e) => setWhatsapp(e.target.value)}
                />
              </Field>
            </div>

            <Field label="Cláusulas Principais">
              <Textarea
                rows={4}
                value={clausulas}
                onChange={(e) => setClausulas(e.target.value)}
              />
            </Field>

            <Field label="Tipo de Locatário *">
              <Select value={tipoLocatario} onValueChange={(v) => setTipoLocatario(v as "PF" | "PJ")}>
                <SelectTrigger>
                  <SelectValue placeholder="Selecione..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="PF">Pessoa Física</SelectItem>
                  <SelectItem value="PJ">Pessoa Jurídica</SelectItem>
                </SelectContent>
              </Select>
            </Field>

            {tipoLocatario === "PJ" && (
              <Field label="Nome do responsável pelo contrato (quem receberá as mensagens) *">
                <Input
                  value={responsavelPJ}
                  onChange={(e) => setResponsavelPJ(e.target.value)}
                  placeholder="Ex: Maria Silva — Diretora Financeira"
                />
              </Field>
            )}

            <div className="flex justify-between pt-2">
              <Button variant="outline" onClick={() => setStep(2)} disabled={saving}>
                Voltar
              </Button>
              <Button onClick={submit} disabled={saving}>
                {saving ? (
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