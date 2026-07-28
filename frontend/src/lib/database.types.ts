// Tipos das tabelas do Supabase usadas pelo painel de gestão.
//
// Escritos à mão a partir de docs/schemas/001_create_tables.sql,
// docs/schemas/002_auth_rbac_rls.sql e docs/schemas/003_ajusta_categorias_clausulas.sql
// — cobrem só as colunas que o frontend realmente usa hoje, não o schema inteiro.
//
// Se o time adotar `supabase gen types typescript` no futuro (requer Supabase
// CLI conectada ao projeto), esse arquivo pode ser substituído pela versão
// gerada automaticamente — mais segura contra o schema divergir do código.

export type GarantiaTipo = "fiador" | "caucao";
export type TipoLocatario = "pf" | "pj";
export type ContractStatus = "ativo" | "inativo" | "pendente_confirmacao";

export interface ContractRow {
  id: string;
  imovel_identificacao: string;
  imovel_endereco: string;
  tipo_locatario: TipoLocatario;
  inquilino_nome: string;
  inquilino_cpf_cnpj: string;
  responsavel_contato_nome: string | null;
  telefone_whatsapp: string;
  fiador_nome: string | null;
  fiador_cpf: string | null;
  fiador_endereco: string | null;
  locatario_endereco: string | null;
  garantia_tipo: GarantiaTipo;
  garantia_valor: number | null;
  valor_aluguel: number;
  dia_vencimento: number;
  data_inicio: string; // date (YYYY-MM-DD)
  data_termino: string; // date (YYYY-MM-DD)
  indice_reajuste: "igpm" | "livre_negociacao" | null;
  data_aniversario_reajuste: string | null; // date
  agua_individualizada: boolean;
  status: ContractStatus;
  observacoes: string | null;
  created_at: string;
  updated_at: string;
}

export type ChargeTipo = "aluguel" | "agua";
export type ChargeStatus =
  | "pendente"
  | "aguardando_confirmacao"
  | "confirmado"
  | "divergente"
  | "atrasado"
  | "em_negociacao"
  | "quitado";

export interface ChargeRow {
  id: string;
  contract_id: string;
  tipo: ChargeTipo;
  mes_referencia: string; // date
  valor_esperado: number;
  valor_identificado: number | null;
  consumo_m3: number | null;
  data_vencimento: string; // date
  data_pagamento: string | null;
  dias_atraso: number;
  status: ChargeStatus;
  comprovante_url: string | null;
  created_at: string;
  updated_at: string;
}

export type TipoResolucaoNegociacao = "perdao_total" | "desconto_parcial" | "negado";

export interface ChargeNegotiationRow {
  id: string;
  charge_id: string;
  tipo_resolucao: TipoResolucaoNegociacao | null;
  valor_negociado: number | null;
  decidido_por_user_id: string;
  data_decisao: string | null;
  created_at: string;
}

export type MaintenanceCategoria = "hidraulica" | "eletrica" | "pintura" | "estrutural" | "outros";
export type MaintenanceUrgencia = "alta" | "media" | "baixa";
export type MaintenanceStatus = "aberto" | "em_andamento" | "resolvido";

export interface MaintenanceTicketRow {
  id: string;
  contract_id: string;
  categoria: MaintenanceCategoria;
  urgencia: MaintenanceUrgencia;
  descricao: string;
  status: MaintenanceStatus;
  observacao: string | null;
  data_abertura: string;
  data_resolucao: string | null;
}

export type ContractAlertTipo = "alerta_renovacao_d60" | "calculo_reajuste_d30";
export type DecisaoGestora = "pendente" | "renovar_sugerido" | "renovar_ajustado" | "encerrar";

export interface ContractAlertRow {
  id: string;
  contract_id: string;
  tipo: ContractAlertTipo;
  data_disparo: string; // date
  percentual_reajuste: number | null;
  valor_sugerido: number | null;
  decisao_gestora: DecisaoGestora | null;
  valor_aplicado: number | null;
  created_at: string;
}
