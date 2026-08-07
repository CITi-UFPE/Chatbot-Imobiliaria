"""Cenários transversais contra o banco real, sem mock: isolamento por RLS
entre contratos (leitura direta de tabela E escrita via RPC), expiração do
JWT do agente, e isolamento de erro no processamento em lote do A4 (um
contrato cuja escrita falhe não pode impedir os demais de serem
processados no mesmo dia — já é o design do try/except por contrato em
app/agents/a4_gestao_contratual/fluxo.py, este é o teste de regressão).
Nenhum destes depende de Claude nem do WhatsApp.
"""

from datetime import date, timedelta

import pytest
from postgrest.exceptions import APIError

from tests.integration.fixtures.contratos import PREFIXO_TELEFONE_FIXTURE

pytestmark = pytest.mark.integration


class TestIsolamentoPorRLS:
    def test_client_escopado_nao_le_contrato_de_outro(
        self, contrato_pf_padrao, contrato_outro_para_isolamento, agente_client_factory
    ):
        contract_id_1 = contrato_pf_padrao["contract_id"]
        contract_id_2 = contrato_outro_para_isolamento["contract_id"]
        client_1 = agente_client_factory(contract_id_1)

        # RLS filtra silenciosamente (0 linhas) — nunca um erro de
        # permissão que denunciasse a EXISTÊNCIA do dado de outro contrato.
        resultado_outro = (
            client_1.table("contracts").select("id").eq("id", contract_id_2).execute()
        )
        assert resultado_outro.data == []

        # O próprio contrato continua visível pelo mesmo client.
        resultado_proprio = (
            client_1.table("contracts").select("id").eq("id", contract_id_1).execute()
        )
        assert len(resultado_proprio.data) == 1

    def test_client_escopado_nao_escreve_charge_de_outro_contrato_via_rpc(
        self,
        contrato_pf_padrao,
        contrato_outro_para_isolamento,
        agente_client_factory,
        service_role_client,
    ):
        """agent_update_charge_status (docs/schemas/011_a2_cobranca_rpcs.sql,
        seção 11.1) filtra por `contract_id = agent_contract_id()` dentro da
        própria função — não é uma checagem em Python. Chamar a RPC com o id
        de uma charge de outro contrato não levanta erro (a função `returns
        void`), só não afeta nenhuma linha: a trava está no banco."""
        contract_id_1 = contrato_pf_padrao["contract_id"]
        contract_id_2 = contrato_outro_para_isolamento["contract_id"]

        charge_outro = (
            service_role_client.table("charges")
            .insert(
                {
                    "contract_id": contract_id_2,
                    "tipo": "aluguel",
                    "mes_referencia": date.today().replace(day=1).isoformat(),
                    "valor_esperado": 999.0,
                    "data_vencimento": date.today().isoformat(),
                    "status": "pendente",
                }
            )
            .execute()
            .data[0]
        )

        client_1 = agente_client_factory(contract_id_1)
        client_1.rpc(
            "agent_update_charge_status",
            {"p_charge_id": charge_outro["id"], "p_status": "confirmado"},
        ).execute()

        charge_depois = (
            service_role_client.table("charges")
            .select("status")
            .eq("id", charge_outro["id"])
            .single()
            .execute()
            .data
        )
        assert charge_depois["status"] == "pendente"


class TestExpiracaoDeJWTDoAgente:
    def test_token_expirado_e_rejeitado_pela_rls(self, contrato_pf_padrao, agente_client_factory):
        """TTL_PADRAO_SEGUNDOS=300 (app/orchestrator/agent_auth.py) — um
        token assinado com exp já no passado deve ser rejeitado pelo
        PostgREST antes mesmo de qualquer política de RLS ser avaliada.

        Margem de -60s (não -10s): o PostgREST tolera uma pequena folga de
        clock skew entre esta máquina e o Supabase — um token expirado há só
        10s ainda passava por essa folga. A partir de -60s a rejeição é
        consistente (validado manualmente com -10/-60/-300/-3600)."""
        contract_id = contrato_pf_padrao["contract_id"]
        client_expirado = agente_client_factory(contract_id, ttl_segundos=-60)

        with pytest.raises(APIError):
            client_expirado.table("contracts").select("id").eq("id", contract_id).execute()


class TestIsolamentoDeErroNoLoteDoA4:
    def test_contrato_com_falha_na_escrita_nao_impede_os_demais(
        self, contrato_prestes_a_vencer, service_role_client, monkeypatch
    ):
        """Um segundo contrato, criado ad hoc (sem fixture dedicada — é
        descartável, só este teste usa), entra na mesma janela D-60 que
        contrato_prestes_a_vencer. Faz o registro do alerta desse segundo
        contrato levantar uma exceção (monkeypatch no nome importado dentro
        de fluxo.py, mesmo padrão de injeção de dependência que o próprio
        módulo já usa nas funções puras processar_*) e confirma que o
        contrato saudável ainda assim recebe seu alerta no mesmo lote."""
        import app.agents.a4_gestao_contratual.fluxo as fluxo_a4

        contract_id_ok = contrato_prestes_a_vencer["contract_id"]
        data_termino = date.fromisoformat(contrato_prestes_a_vencer["dados"]["data_termino"])
        hoje = data_termino - timedelta(days=60)

        telefone_falho = f"{PREFIXO_TELEFONE_FIXTURE}009"
        dados_falho = {
            "imovel_identificacao": "Apto Fixture Falho",
            "imovel_endereco": "Rua de Teste, 100 — Recife/PE",
            "tipo_locatario": "pf",
            "inquilino_nome": "Fixture Falho",
            "inquilino_cpf_cnpj": "00000000002",
            "garantia_tipo": "fiador",
            "fiador_nome": "Fiador Falho",
            "fiador_cpf": "22222222222",
            "valor_aluguel": 1500.0,
            "dia_vencimento": 10,
            "vencimento_mes_referencia": "atual",
            "data_inicio": (hoje - timedelta(days=305)).isoformat(),
            "data_termino": data_termino.isoformat(),
            "indice_reajuste": "livre_negociacao",
            "multa_infracao_tipo": "meses_aluguel",
            "multa_infracao_valor": 3,
            "juros_moratorio_mensal": 0.01,
            "aviso_previo_dias": 30,
            "aviso_previo_a_partir_mes": 1,
            "status": "ativo",
            "telefone_whatsapp": telefone_falho,
        }
        contract_id_falho = (
            service_role_client.table("contracts").insert(dados_falho).execute().data[0]["id"]
        )

        try:
            real_registrar = fluxo_a4.registrar_alerta_renovacao

            def _registrar_com_falha_para_um_contrato(contract_id, data_disparo):
                if str(contract_id) == str(contract_id_falho):
                    raise RuntimeError("falha simulada de escrita")
                return real_registrar(contract_id, data_disparo)

            monkeypatch.setattr(
                fluxo_a4, "registrar_alerta_renovacao", _registrar_com_falha_para_um_contrato
            )

            resultado = fluxo_a4.executar_alertas_contratuais(hoje=hoje)

            assert len(resultado.alertas_renovacao) == 1  # só o contrato saudável
            assert any(
                str(contract_id_falho) in erro and "alerta de renovação" in erro
                for erro in resultado.erros
            )

            alerta_ok = (
                service_role_client.table("contract_alerts")
                .select("id")
                .eq("contract_id", contract_id_ok)
                .execute()
                .data
            )
            assert len(alerta_ok) == 1

            alerta_falho = (
                service_role_client.table("contract_alerts")
                .select("id")
                .eq("contract_id", contract_id_falho)
                .execute()
                .data
            )
            assert alerta_falho == []
        finally:
            service_role_client.table("contracts").delete().eq(
                "telefone_whatsapp", telefone_falho
            ).execute()
