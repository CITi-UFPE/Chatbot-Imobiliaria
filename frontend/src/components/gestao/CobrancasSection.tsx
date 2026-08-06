import { useState } from "react";
import { toast } from "sonner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, HandCoins, Wallet, ChevronDown, ChevronUp } from "lucide-react";
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
const ATRASADAS_QUERY_KEY = ["charges-em-atraso"] as const;
const PENDENTES_QUERY_KEY = ["charges-pendentes"] as const;

type Tipo = "" | "total" | "parcial" | "negado";

const TIPO_TO_RESOLUCAO: Record<Exclude<Tipo, "">, TipoResolucaoNegociacao> = {
  total: "perdao_total",
  parcial: "desconto_parcial",
  negado: "negado",
};

// Evita o bug de fuso horário do JS: new Date("2025-06-01") é interpretado
// como UTC e, ao formatar no fuso local (Brasil, UTC-3), pode "voltar" um
// dia — junho vira maio. Construindo a partir de ano/mês/dia numéricos,
// o Date já nasce no fuso local e a formatação fica correta.
function formatarMesReferencia(mesReferenciaISO: string): string {
  const [ano, mes] = mesReferenciaISO.split("-").map(Number);
  return new Date(ano, mes - 1, 1).toLocaleDateString("pt-BR", {
    month: "long",
    year: "numeric",
  });
}

// Mesmo problema de fuso horário do formatarMesReferencia acima, aplicado
// a datas completas (dia/mês/ano) em vez de só mês/ano.
function formatarDataVencimento(dataISO: string): string {
  const [ano, mes, dia] = dataISO.split("-").map(Number);
  return new Date(ano, mes - 1, dia).toLocaleDateString("pt-BR");
}

// Formata um valor monetário em Reais, sempre com exatamente 2 casas
// decimais. Sem maximumFractionDigits, toLocaleString usa como teto o
// maior valor entre minimumFractionDigits e 3 — resíduo de ponto
// flutuante em contas com multa/juros (ex: 26.008 em vez de 26.01)
// aparecia na tela como "R$ 26,008". Centralizado aqui pra não repetir
// as duas opções em cada toLocaleString do arquivo.
function formatarValorBRL(valor: number): string {
  return valor.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

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

// Linha de charge em atraso (status='atrasado'), com o valor final já
// calculado (inicial + multa + juros) seguindo a MESMA fórmula de
// app/agents/a2_cobranca/mensagens.py:_calcular_encargos — precisa manter
// as duas em sincronia se a fórmula mudar de um lado.
interface Atraso {
  chargeId: string;
  contractId: string;
  inquilino: string;
  imovel: string;
  telefone: string | null;
  mes: string;
  diasAtraso: number;
  valorInicial: number;
  valorFinal: number;
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
    mes: formatarMesReferencia(row.mes_referencia),
    valor: Number(row.valor_esperado),
  }));
}

// Linha de charge ainda não vencida/atrasada (status='pendente'). Sem
// cálculo de multa/juros — isso só existe pra charges já em atraso — por
// isso o campo é só "valorEsperado", sem o par valorInicial/valorFinal do
// Atraso. Usada pra resolução manual (comprovante enviado direto pra
// gestão do imóvel, fora do fluxo automático de cobrança do A2).
interface Pendente {
  chargeId: string;
  contractId: string;
  inquilino: string;
  imovel: string;
  telefone: string | null;
  mes: string;
  dataVencimento: string; // ISO (yyyy-mm-dd), como vem de charges.data_vencimento
  valorEsperado: number;
}

async function fetchPendentes(): Promise<Pendente[]> {
  const { data, error } = await supabase
    .from("charges")
    .select(
      "id, contract_id, mes_referencia, valor_esperado, data_vencimento, contracts(inquilino_nome, imovel_endereco, telefone_whatsapp)",
    )
    .eq("status", "pendente")
    .order("data_vencimento", { ascending: true });

  if (error) throw error;

  return (data ?? []).map((row: any) => ({
    chargeId: row.id,
    contractId: row.contract_id,
    inquilino: row.contracts?.inquilino_nome ?? "—",
    imovel: row.contracts?.imovel_endereco ?? "—",
    telefone: row.contracts?.telefone_whatsapp ?? null,
    mes: formatarMesReferencia(row.mes_referencia),
    dataVencimento: row.data_vencimento,
    valorEsperado: Number(row.valor_esperado),
  }));
}

// Mesma convenção assumida em mensagens.py: multa_moratoria_percentual é
// fração (0.02 = 2%), não percentual inteiro. Juros prorateado num mês de
// 30 dias. Ver nota de unidade ainda pendente na Migration 011/003 — se a
// convenção mudar de um lado, precisa mudar dos dois.
//
// O resultado é arredondado para centavos (2 casas decimais, arredondamento
// padrão) antes de retornar. Sem isso, a soma de
// frações (multa + juros prorateados por dia) produz resíduo de ponto
// flutuante (ex: 26.008000000000003) que aparecia quebrado na tela.
// Arredondar sempre pra cima cobraria sistematicamente um pouco a mais do
// inquilino a cada atraso — arredondamento padrão é a prática usual em
// cobranças financeiras e não favorece nenhum dos lados.
function calcularValorFinal(
  valorEsperado: number,
  diasAtraso: number,
  multaPercentual: number | null,
  jurosMensal: number,
): number {
  const percentualMulta = multaPercentual ?? 0;
  const valorMulta = valorEsperado * percentualMulta;
  const valorJuros = valorEsperado * jurosMensal * (diasAtraso / 30);
  const valorBruto = valorEsperado + valorMulta + valorJuros;
  return Math.round(valorBruto * 100) / 100;
}

async function fetchAtrasadas(): Promise<Atraso[]> {
  const { data, error } = await supabase
    .from("charges")
    .select(
      "id, contract_id, mes_referencia, valor_esperado, dias_atraso, contracts(inquilino_nome, imovel_endereco, telefone_whatsapp, multa_moratoria_percentual, juros_moratorio_mensal)",
    )
    .eq("status", "atrasado")
    .order("dias_atraso", { ascending: false });

  if (error) throw error;

  return (data ?? []).map((row: any) => {
    const valorEsperado = Number(row.valor_esperado);
    const diasAtraso = Number(row.dias_atraso ?? 0);
    return {
      chargeId: row.id,
      contractId: row.contract_id,
      inquilino: row.contracts?.inquilino_nome ?? "—",
      imovel: row.contracts?.imovel_endereco ?? "—",
      telefone: row.contracts?.telefone_whatsapp ?? null,
      mes: formatarMesReferencia(row.mes_referencia),
      diasAtraso,
      valorInicial: valorEsperado,
      valorFinal: calcularValorFinal(
        valorEsperado,
        diasAtraso,
        row.contracts?.multa_moratoria_percentual ?? null,
        row.contracts?.juros_moratorio_mensal ?? 0,
      ),
    };
  });
}

// Estado local só do formulário de resolução (tipo escolhido, valor digitado)
// — não é dado do banco, por isso continua em useState em vez de query.
interface FormState {
  tipo: Tipo;
  valorNegociado: string;
}

// Estado local do formulário de "Marcar como Pago" (data e valor
// efetivamente recebidos) — também não é dado do banco, mora em useState.
// Data default = hoje (editável); valor default = valorFinal calculado
// (editável, é só um chute inicial pra poupar digitação).
interface PagamentoFormState {
  dataPagamento: string;
  valorPago: string;
}

function hojeISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function AtrasoCard({
  n,
  isPending,
  form,
  onChangeForm,
  onMarcarPago,
}: {
  n: Atraso;
  isPending: boolean;
  form: PagamentoFormState;
  onChangeForm: (patch: Partial<PagamentoFormState>) => void;
  onMarcarPago: () => void;
}) {
  const valorInvalido = form.valorPago !== "" && Number(form.valorPago) <= 0;

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
        <Badge className="border-red-200 bg-red-50 text-red-700 hover:bg-red-50 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
          {n.diasAtraso} dias em atraso
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-xs uppercase text-muted-foreground">Mês de Referência</div>
            <div className="font-medium">{n.mes}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted-foreground">Valor Original</div>
            <div className="font-medium tnum">R$ {formatarValorBRL(n.valorInicial)}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted-foreground">Valor Atualizado (hoje)</div>
            <div className="font-semibold text-lg tnum">R$ {formatarValorBRL(n.valorFinal)}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted-foreground">Telefone</div>
            <div className="font-medium">
              {n.telefone ?? <span className="text-muted-foreground italic">Não Registrado</span>}
            </div>
          </div>
        </div>

        <div className="grid sm:grid-cols-[1fr,1fr,auto] gap-3 items-end pt-2 border-t">
          <div className="space-y-1.5">
            <Label>Data do Pagamento</Label>
            <Input
              type="date"
              value={form.dataPagamento}
              onChange={(e) => onChangeForm({ dataPagamento: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Valor Pago (R$)</Label>
            <Input
              type="number"
              step="0.01"
              placeholder="0,00"
              value={form.valorPago}
              onChange={(e) => onChangeForm({ valorPago: e.target.value })}
              aria-invalid={valorInvalido}
            />
          </div>
          <Button
            onClick={onMarcarPago}
            disabled={isPending || !form.dataPagamento || !form.valorPago || valorInvalido}
          >
            {isPending ? "Confirmando..." : "Marcar como Pago"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function PendenteCard({
  n,
  isPending,
  form,
  onChangeForm,
  onMarcarPago,
}: {
  n: Pendente;
  isPending: boolean;
  form: PagamentoFormState;
  onChangeForm: (patch: Partial<PagamentoFormState>) => void;
  onMarcarPago: () => void;
}) {
  const valorInvalido = form.valorPago !== "" && Number(form.valorPago) <= 0;

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
        <Badge variant="outline">
          Vence {formatarDataVencimento(n.dataVencimento)}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-xs uppercase text-muted-foreground">Mês de Referência</div>
            <div className="font-medium">{n.mes}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted-foreground">Valor Esperado</div>
            <div className="font-semibold text-lg tnum">R$ {formatarValorBRL(n.valorEsperado)}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted-foreground">Vencimento</div>
            <div className="font-medium">
              {formatarDataVencimento(n.dataVencimento)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase text-muted-foreground">Telefone</div>
            <div className="font-medium">
              {n.telefone ?? <span className="text-muted-foreground italic">Não Registrado</span>}
            </div>
          </div>
        </div>

        <div className="grid sm:grid-cols-[1fr,1fr,auto] gap-3 items-end pt-2 border-t">
          <div className="space-y-1.5">
            <Label>Data do Pagamento</Label>
            <Input
              type="date"
              value={form.dataPagamento}
              onChange={(e) => onChangeForm({ dataPagamento: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Valor Pago (R$)</Label>
            <Input
              type="number"
              step="0.01"
              placeholder="0,00"
              value={form.valorPago}
              onChange={(e) => onChangeForm({ valorPago: e.target.value })}
              aria-invalid={valorInvalido}
            />
          </div>
          <Button
            onClick={onMarcarPago}
            disabled={isPending || !form.dataPagamento || !form.valorPago || valorInvalido}
          >
            {isPending ? "Confirmando..." : "Marcar como Pago"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// Cabeçalho clicável reutilizado pelas quatro seções da tela — cada uma
// controla seu próprio booleano de aberto/fechado (openSections), então
// recolher uma não afeta as outras.
function SectionToggle({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={onClick}
      aria-label={open ? "Recolher seção" : "Expandir seção"}
      className="shrink-0 mt-1"
    >
      {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
    </Button>
  );
}

export function CobrancasSection() {
  const queryClient = useQueryClient();
  const [forms, setForms] = useState<Record<string, FormState>>({});
  const [pagamentoForms, setPagamentoForms] = useState<Record<string, PagamentoFormState>>({});
  const [pagamentoFormsPendentes, setPagamentoFormsPendentes] = useState<
    Record<string, PagamentoFormState>
  >({});

  // Controla individualmente se cada uma das 4 seções está aberta ou
  // fechada — todas começam abertas.
  const [openSections, setOpenSections] = useState({
    negociacao: true,
    pendentes: true,
    atrasoLeve: true,
    atrasoCritico: true,
  });
  const toggleSection = (key: keyof typeof openSections) =>
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));

  const { data: items = [], isLoading, isError } = useQuery({
    queryKey: COBRANCAS_QUERY_KEY,
    queryFn: fetchNegociacoes,
  });

  const {
    data: pendentes = [],
    isLoading: isLoadingPendentes,
    isError: isErrorPendentes,
  } = useQuery({
    queryKey: PENDENTES_QUERY_KEY,
    queryFn: fetchPendentes,
  });

  const {
    data: atrasadas = [],
    isLoading: isLoadingAtrasadas,
    isError: isErrorAtrasadas,
  } = useQuery({
    queryKey: ATRASADAS_QUERY_KEY,
    queryFn: fetchAtrasadas,
  });

  const atrasadasLeves = atrasadas.filter((a) => a.diasAtraso <= 14);
  const atrasadasCriticas = atrasadas.filter((a) => a.diasAtraso >= 15);

  const getForm = (id: string): FormState => forms[id] ?? { tipo: "", valorNegociado: "" };
  const updateForm = (id: string, patch: Partial<FormState>) =>
    setForms((prev) => ({ ...prev, [id]: { ...getForm(id), ...patch } }));

  // valorFinal só existe depois que "atrasadas" carrega, por isso o default
  // do valor pago é aplicado sob demanda (getPagamentoForm), não no useState inicial.
  const getPagamentoForm = (n: Atraso): PagamentoFormState =>
    pagamentoForms[n.chargeId] ?? {
      dataPagamento: hojeISO(),
      valorPago: n.valorFinal.toFixed(2),
    };
  const updatePagamentoForm = (n: Atraso, patch: Partial<PagamentoFormState>) =>
    setPagamentoForms((prev) => ({
      ...prev,
      [n.chargeId]: { ...getPagamentoForm(n), ...patch },
    }));

  // Mesmo padrão do getPagamentoForm/updatePagamentoForm de atrasadas,
  // mas com estado separado (pagamentoFormsPendentes) — aqui o default do
  // valor é valorEsperado puro (sem multa/juros, charge ainda não está em
  // atraso).
  const getPagamentoFormPendente = (n: Pendente): PagamentoFormState =>
    pagamentoFormsPendentes[n.chargeId] ?? {
      dataPagamento: hojeISO(),
      valorPago: n.valorEsperado.toFixed(2),
    };
  const updatePagamentoFormPendente = (n: Pendente, patch: Partial<PagamentoFormState>) =>
    setPagamentoFormsPendentes((prev) => ({
      ...prev,
      [n.chargeId]: { ...getPagamentoFormPendente(n), ...patch },
    }));

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

      // Bug conhecido (corrigido aqui): o valor da cobrança nunca era
      // atualizado após a negociação — charge_negotiations guardava o
      // valor combinado só no histórico, mas charges.valor_esperado
      // continuava com o valor cheio pra sempre, inflando relatórios que
      // somam esse campo.
      //
      // "Perdão Total" grava 0.01, não 0: a coluna tem
      // `check (valor_esperado > 0)` (Migration 001), então um update pra
      // 0 exato violaria a constraint. 0.01 é o menor valor que passa
      // nessa constraint sem precisar relaxá-la — é um "quase-zero"
      // técnico, não um valor de negócio real. Qualquer relatório que some
      // valor_esperado vai carregar esse resíduo de R$0,01 por perdão
      // total; se isso incomodar em relatórios financeiros, a saída limpa
      // é migrar a constraint pra `>= 0` (ou separar num campo
      // valor_final) e voltar a gravar 0 exato.
      //
      // "Negado" não muda o valor (a cobrança segue em aberto pelo valor
      // original).
      const PERDAO_TOTAL_VALOR_RESIDUAL = 0.01;
      const updatePayload: { status: string; valor_esperado?: number } = {
        status: novoStatusCharge,
      };
      if (form.tipo === "total") {
        updatePayload.valor_esperado = PERDAO_TOTAL_VALOR_RESIDUAL;
      } else if (form.tipo === "parcial") {
        updatePayload.valor_esperado = valorNegociado as number;
      }

      const { error: chargeError } = await supabase
        .from("charges")
        .update(updatePayload)
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

  // Marcar como pago manualmente: fecha o ciclo fora do fluxo de
  // negociação (Fernanda resolveu por telefone/comprovante direto).
  // status='quitado' já é suficiente pra parar as cobranças automáticas,
  // porque cron_listar_charges_ativas (Migration 008) exclui
  // status='quitado' da varredura diária — nenhuma mudança no cron ou nas
  // RPCs é necessária.
  // data_pagamento e valor_identificado agora vêm do formulário (usuário
  // informa o que realmente aconteceu), em vez de data fixa "hoje" e
  // valor null.
  const marcarPagoMutation = useMutation({
    mutationFn: async ({
      chargeId,
      dataPagamento,
      valorPago,
    }: {
      chargeId: string;
      dataPagamento: string;
      valorPago: number;
    }) => {
      const { error } = await supabase
        .from("charges")
        .update({
          status: "quitado",
          data_pagamento: dataPagamento,
          valor_identificado: valorPago,
        })
        .eq("id", chargeId);
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success("Cobrança marcada como paga", {
        description: "As mensagens automáticas de cobrança para este mês foram interrompidas.",
        icon: <MessageCircle className="h-4 w-4" />,
      });
      queryClient.invalidateQueries({ queryKey: ATRASADAS_QUERY_KEY });
    },
    onError: (error: Error) => {
      console.error("Erro ao marcar cobrança como paga:", error);
      toast.error(error.message || "Não foi possível marcar como paga. Tente novamente.");
    },
  });

  const handleMarcarPago = (n: Atraso) => {
    const form = getPagamentoForm(n);
    const valorPago = Number(form.valorPago);
    if (!form.dataPagamento || !valorPago || valorPago <= 0) {
      toast.error("Informe a data e o valor pago antes de confirmar.");
      return;
    }
    marcarPagoMutation.mutate({
      chargeId: n.chargeId,
      dataPagamento: form.dataPagamento,
      valorPago,
    });
  };

  // Resolução manual pra charges ainda não vencidas/atrasadas — mesmo
  // caso de uso do marcarPagoMutation acima (comprovante enviado direto
  // pra gestão, fora do fluxo automático), mutation própria só pra manter
  // a invalidação de query separada (PENDENTES_QUERY_KEY em vez de
  // ATRASADAS_QUERY_KEY).
  const marcarPagoPendenteMutation = useMutation({
    mutationFn: async ({
      chargeId,
      dataPagamento,
      valorPago,
    }: {
      chargeId: string;
      dataPagamento: string;
      valorPago: number;
    }) => {
      const { error } = await supabase
        .from("charges")
        .update({
          status: "quitado",
          data_pagamento: dataPagamento,
          valor_identificado: valorPago,
        })
        .eq("id", chargeId);
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success("Cobrança marcada como paga", {
        description: "Pagamento confirmado direto com a gestão, fora do fluxo automático de cobrança.",
        icon: <MessageCircle className="h-4 w-4" />,
      });
      queryClient.invalidateQueries({ queryKey: PENDENTES_QUERY_KEY });
    },
    onError: (error: Error) => {
      console.error("Erro ao marcar cobrança pendente como paga:", error);
      toast.error(error.message || "Não foi possível marcar como paga. Tente novamente.");
    },
  });

  const handleMarcarPagoPendente = (n: Pendente) => {
    const form = getPagamentoFormPendente(n);
    const valorPago = Number(form.valorPago);
    if (!form.dataPagamento || !valorPago || valorPago <= 0) {
      toast.error("Informe a data e o valor pago antes de confirmar.");
      return;
    }
    marcarPagoPendenteMutation.mutate({
      chargeId: n.chargeId,
      dataPagamento: form.dataPagamento,
      valorPago,
    });
  };

  return (
    <div className="space-y-10">
      <div>
        <div className="flex items-start justify-between gap-4">
          <PageHeader
            title="Cobranças em Negociação"
            description="Gerencie perdões, descontos parciais e negações."
          />
          <SectionToggle
            open={openSections.negociacao}
            onClick={() => toggleSection("negociacao")}
          />
        </div>
        {openSections.negociacao && (
        <>
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
                      <div className="font-semibold text-lg tnum">R$ {formatarValorBRL(n.valor)}</div>
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
        </>
        )}
      </div>

      <div>
        <div className="flex items-start justify-between gap-4">
          <PageHeader
            title="Cobranças em Dia (Resolução Manual)"
            description="Ainda não vencidas ou não atrasadas. Cobrança resolvida manualmente (comprovante enviado direto pra gestão, fora do fluxo automático de cobrança)."
          />
          <SectionToggle
            open={openSections.pendentes}
            onClick={() => toggleSection("pendentes")}
          />
        </div>
        {openSections.pendentes && (
        <>
        <div className="grid gap-4 sm:grid-cols-2 mb-6">
          <StatTile
            tone="c"
            icon={<HandCoins className="h-5 w-5" />}
            label="Em Dia"
            value={pendentes.length}
            sublabel="Cobranças aguardando vencimento"
          />
          <StatTile
            tone="b"
            icon={<Wallet className="h-5 w-5" />}
            label="Valor Total"
            value={`R$ ${formatarValorBRL(pendentes.reduce((acc, n) => acc + n.valorEsperado, 0))}`}
            sublabel="Somado das cobranças em dia"
          />
        </div>
        {isErrorPendentes && (
          <p className="text-sm text-destructive mb-4">
            Não foi possível carregar as cobranças pendentes.
          </p>
        )}
        <div className="grid gap-4">
          {isLoadingPendentes && (
            <p className="text-sm text-muted-foreground text-center py-8">Carregando...</p>
          )}
          {pendentes.map((n) => (
            <PendenteCard
              key={n.chargeId}
              n={n}
              isPending={
                marcarPagoPendenteMutation.isPending &&
                marcarPagoPendenteMutation.variables?.chargeId === n.chargeId
              }
              form={getPagamentoFormPendente(n)}
              onChangeForm={(patch) => updatePagamentoFormPendente(n, patch)}
              onMarcarPago={() => handleMarcarPagoPendente(n)}
            />
          ))}
          {!isLoadingPendentes && pendentes.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              Nenhuma cobrança pendente aguardando vencimento.
            </p>
          )}
        </div>
        </>
        )}
      </div>

      <div>
        <div className="flex items-start justify-between gap-4">
          <PageHeader
            title="Em Atraso (1-14 dias)"
            description="Cobranças ainda dentro do fluxo automático de mensagens."
          />
          <SectionToggle
            open={openSections.atrasoLeve}
            onClick={() => toggleSection("atrasoLeve")}
          />
        </div>
        {openSections.atrasoLeve && (
        <>
        <div className="grid gap-4 sm:grid-cols-2 mb-6">
          <StatTile
            tone="c"
            icon={<HandCoins className="h-5 w-5" />}
            label="Em Atraso Leve"
            value={atrasadasLeves.length}
            sublabel="Cobranças de 1 a 14 dias"
          />
          <StatTile
            tone="b"
            icon={<Wallet className="h-5 w-5" />}
            label="Valor Total"
            value={`R$ ${formatarValorBRL(atrasadasLeves.reduce((acc, n) => acc + n.valorFinal, 0))}`}
            sublabel="Somado das cobranças em atraso leve"
          />
        </div>
        {isErrorAtrasadas && (
          <p className="text-sm text-destructive mb-4">
            Não foi possível carregar as cobranças em atraso.
          </p>
        )}
        <div className="grid gap-4">
          {isLoadingAtrasadas && (
            <p className="text-sm text-muted-foreground text-center py-8">Carregando...</p>
          )}
          {atrasadasLeves.map((n) => (
            <AtrasoCard
              key={n.chargeId}
              n={n}
              isPending={
                marcarPagoMutation.isPending &&
                marcarPagoMutation.variables?.chargeId === n.chargeId
              }
              form={getPagamentoForm(n)}
              onChangeForm={(patch) => updatePagamentoForm(n, patch)}
              onMarcarPago={() => handleMarcarPago(n)}
            />
          ))}
          {!isLoadingAtrasadas && atrasadasLeves.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              Nenhuma cobrança em atraso de 1 a 14 dias.
            </p>
          )}
        </div>
        </>
        )}
      </div>

      <div>
        <div className="flex items-start justify-between gap-4">
          <PageHeader
            title="Em Atraso Crítico (15+ dias)"
            description="Cobrança já escalonada — resolução manual necessária."
          />
          <SectionToggle
            open={openSections.atrasoCritico}
            onClick={() => toggleSection("atrasoCritico")}
          />
        </div>
        {openSections.atrasoCritico && (
        <>
        <div className="grid gap-4 sm:grid-cols-2 mb-6">
          <StatTile
            tone="c"
            icon={<HandCoins className="h-5 w-5" />}
            label="Atraso Crítico"
            value={atrasadasCriticas.length}
            sublabel="Cobranças de 15+ dias"
          />
          <StatTile
            tone="b"
            icon={<Wallet className="h-5 w-5" />}
            label="Valor Total"
            value={`R$ ${formatarValorBRL(atrasadasCriticas.reduce((acc, n) => acc + n.valorFinal, 0))}`}
            sublabel="Somado das cobranças em atraso crítico"
          />
        </div>
        <div className="grid gap-4">
          {atrasadasCriticas.map((n) => (
            <AtrasoCard
              key={n.chargeId}
              n={n}
              isPending={
                marcarPagoMutation.isPending &&
                marcarPagoMutation.variables?.chargeId === n.chargeId
              }
              form={getPagamentoForm(n)}
              onChangeForm={(patch) => updatePagamentoForm(n, patch)}
              onMarcarPago={() => handleMarcarPago(n)}
            />
          ))}
          {!isLoadingAtrasadas && atrasadasCriticas.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              Nenhuma cobrança em atraso crítico.
            </p>
          )}
        </div>
        </>
        )}
      </div>
    </div>
  );
}