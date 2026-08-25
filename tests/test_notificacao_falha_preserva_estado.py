"""Regressão dos achados do code-review na WA-05/WA-06: em
app/agents/a2_cobranca/cobranca.py, app/agents/a5_escalonamento/
escalonamento.py e app/agents/a2_cobranca/comprovante.py, a gravação no
banco acontecia ANTES do aviso por WhatsApp, mas se o aviso falhasse a
exceção subia e "apagava" o efeito da gravação aos olhos de quem chamou —
mesmo o dado já estando salvo de verdade. Estes testes fixam o
comportamento corrigido: falha de transporte é logada, mas nunca desfaz
nem esconde um efeito de negócio que já aconteceu.

O caso de comprovante.py (TestResolverChargeENotificarSobreviveAFalha
abaixo) foi encontrado no code-review da WA-06 e ficou pendente até agora
— era explicitamente citado na docstring de _resolver_charge_e_notificar
como "mesmo padrão do achado já corrigido" nos outros dois módulos, mas
nunca tinha sido corrigido ali de fato.

Só mocka a camada que fala com o Supabase (obter_client_agente /
obter_client_cron_batch) e o transporte de WhatsApp (enviar_mensagem_cobranca
/ notificar_staff / notificar_fernanda_*) — mesmo padrão de
tests/testar_a2_manual.py.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app.agents.a2_cobranca.comprovante import _resolver_charge_e_notificar
from app.agents.a2_cobranca.schemas import ComprovanteExtraido
from app.agents.a5_escalonamento.escalonamento import AvaliacaoEscalonamento, executar_escalonamento

HOJE = date(2026, 7, 17)

DADOS_CONTRATO_PADRAO = {
    "telefone_whatsapp": "+5581999990000",
    "inquilino_nome": "João Pereira",
    "imovel_identificacao": "Apto 305, Ed. Girassol",
    "multa_moratoria_percentual": 0.02,
    "juros_moratorio_mensal": 0.01,
}


def _charge_raw(*, dias_offset: int, status: str, mensagem_estagio, dias_atraso_salvo: int) -> dict:
    vencimento = HOJE - timedelta(days=dias_offset)
    return {
        "contract_id": "11111111-1111-1111-1111-111111111111",
        "charge_id": "charge-teste",
        "tipo": "aluguel",
        "mes_referencia": vencimento.replace(day=1).isoformat(),
        "valor_esperado": 2200.0,
        "data_vencimento": vencimento.isoformat(),
        "data_pagamento": None,
        "dias_atraso": dias_atraso_salvo,
        "status": status,
        "mensagem_estagio": mensagem_estagio,
    }


def _client_agente_fake(updates_registrados: list) -> MagicMock:
    client = MagicMock()

    def _rpc(nome_funcao: str, parametros: dict):
        builder = MagicMock()
        if nome_funcao == "buscar_dados_cobranca_contrato":
            builder.execute.return_value = MagicMock(data=DADOS_CONTRATO_PADRAO)
        elif nome_funcao == "agent_update_charge_status":
            updates_registrados.append(parametros)
            builder.execute.return_value = MagicMock(data=None)
        else:
            raise ValueError(f"RPC não mockada neste teste: {nome_funcao}")
        return builder

    client.rpc.side_effect = _rpc
    return client


class TestFalhaDeEnvioNaoBloqueiaRecalculoDiarioDoCron:
    def test_d5_falha_no_envio_ainda_atualiza_dias_atraso_e_status(self):
        """D-5 simples: mesmo se o WhatsApp falhar, dias_atraso/status têm
        que ser recalculados hoje (não podem ficar travados esperando o
        envio dar certo)."""
        charge_raw = _charge_raw(
            dias_offset=-5, status="pendente", mensagem_estagio=None, dias_atraso_salvo=999
        )
        updates: list = []
        client_agente_fake = _client_agente_fake(updates)

        with patch(
            "app.agents.a2_cobranca.cobranca.obter_client_agente", return_value=client_agente_fake
        ), patch(
            "app.agents.a2_cobranca.cobranca.enviar_mensagem_cobranca",
            side_effect=RuntimeError("Meta fora do ar"),
        ):
            from app.agents.a2_cobranca.cobranca import _processar_charge

            _processar_charge(charge_raw, HOJE)  # não deve levantar

        assert len(updates) == 1
        assert updates[0]["p_dias_atraso"] == -5
        assert updates[0]["p_status"] == "pendente"
        # mensagem_estagio NÃO avança pra "d-5" — o envio falhou, então o
        # cron de amanhã precisa continuar achando que ainda não mandou.
        assert updates[0]["p_mensagem_estagio"] is None

    def test_d15_falha_no_envio_nao_marca_estagio_nem_escala(self):
        """D+15: se o envio falhar, nem o estágio pode ser marcado como
        enviado, nem o escalonamento automático pode disparar — os dois
        dependem da mensagem ter saído de verdade."""
        charge_raw = _charge_raw(
            dias_offset=15, status="atrasado", mensagem_estagio="d+10", dias_atraso_salvo=10
        )
        updates: list = []
        client_agente_fake = _client_agente_fake(updates)
        escalonamentos: list = []

        with patch(
            "app.agents.a2_cobranca.cobranca.obter_client_agente", return_value=client_agente_fake
        ), patch(
            "app.agents.a2_cobranca.cobranca.enviar_mensagem_cobranca",
            side_effect=RuntimeError("Meta fora do ar"),
        ), patch(
            "app.agents.a2_cobranca.cobranca.executar_escalonamento",
            side_effect=lambda *a, **k: escalonamentos.append((a, k)),
        ):
            from app.agents.a2_cobranca.cobranca import _processar_charge

            _processar_charge(charge_raw, HOJE)

        assert len(updates) == 1
        assert updates[0]["p_dias_atraso"] == 15
        assert updates[0]["p_status"] == "atrasado"
        assert updates[0]["p_mensagem_estagio"] == "d+10"  # continua o antigo, não virou "d+15"
        assert escalonamentos == []  # não escala sem a mensagem ter saído

    def test_d15_sucesso_no_envio_marca_estagio_e_escala_normalmente(self):
        """Regressão de compatibilidade: quando o envio dá certo, o
        comportamento continua o mesmo de antes da correção — estágio
        avança e o escalonamento automático dispara."""
        charge_raw = _charge_raw(
            dias_offset=15, status="atrasado", mensagem_estagio="d+10", dias_atraso_salvo=10
        )
        updates: list = []
        client_agente_fake = _client_agente_fake(updates)
        escalonamentos: list = []

        with patch(
            "app.agents.a2_cobranca.cobranca.obter_client_agente", return_value=client_agente_fake
        ), patch(
            "app.agents.a2_cobranca.cobranca.enviar_mensagem_cobranca", return_value=None
        ), patch(
            "app.agents.a2_cobranca.cobranca.executar_escalonamento",
            side_effect=lambda contract_id, avaliacao: escalonamentos.append((contract_id, avaliacao)),
        ):
            from app.agents.a2_cobranca.cobranca import _processar_charge

            _processar_charge(charge_raw, HOJE)

        assert updates[0]["p_mensagem_estagio"] == "d+15"
        assert len(escalonamentos) == 1
        assert escalonamentos[0][1].motivo == "atraso_severo"


class TestExecutarEscalonamentoSobreviveAFalhaDeNotificacao:
    def test_falha_ao_notificar_staff_nao_apaga_protocolo_ja_gravado(self):
        client_fake = MagicMock()
        client_fake.rpc.return_value.execute.return_value = MagicMock(data="ESC-2026-00042")

        avaliacao = AvaliacaoEscalonamento(
            motivo="pedido_humano",
            descricao="Inquilino pediu falar com uma pessoa.",
            resposta_para_inquilino="Encaminhamos seu caso para a equipe.",
        )

        with patch(
            "app.agents.a5_escalonamento.escalonamento.obter_client_agente", return_value=client_fake
        ), patch(
            "app.agents.a5_escalonamento.escalonamento.notificar_staff_escalonamento",
            side_effect=RuntimeError("Meta fora do ar"),
        ):
            protocolo = executar_escalonamento("22222222-2222-2222-2222-222222222222", avaliacao)

        # A escalação já estava gravada no banco (RPC acima) — o protocolo
        # tem que voltar pro chamador mesmo com o aviso à equipe falhando.
        assert protocolo == "ESC-2026-00042"

    def test_sucesso_ao_notificar_staff_continua_funcionando_normalmente(self):
        client_fake = MagicMock()
        client_fake.rpc.return_value.execute.return_value = MagicMock(data="ESC-2026-00043")
        chamadas_staff: list = []

        avaliacao = AvaliacaoEscalonamento(
            motivo="ameaca_juridica",
            descricao="Inquilino ameaçou processar a imobiliária.",
            resposta_para_inquilino="Seu caso foi encaminhado para a equipe.",
        )

        with patch(
            "app.agents.a5_escalonamento.escalonamento.obter_client_agente", return_value=client_fake
        ), patch(
            "app.agents.a5_escalonamento.escalonamento.notificar_staff_escalonamento",
            side_effect=lambda protocolo, motivo, descricao: chamadas_staff.append(
                (protocolo, motivo, descricao)
            ),
        ):
            protocolo = executar_escalonamento("33333333-3333-3333-3333-333333333333", avaliacao)

        assert protocolo == "ESC-2026-00043"
        assert len(chamadas_staff) == 1
        assert chamadas_staff[0][0] == "ESC-2026-00043"


class TestResolverChargeENotificarSobreviveAFalha:
    """comprovante.py::_resolver_charge_e_notificar — Caso A, B.a e B.b são
    os três ramos em que _marcar_aguardando_confirmacao (grava no banco)
    roda ANTES do notificar_fernanda_*. Uma falha de transporte não pode
    apagar, aos olhos de quem chama, o fato de que a charge já mudou de
    status de verdade."""

    CONTRACT_ID = "44444444-4444-4444-4444-444444444444"
    DADOS_CONTRATO = {"inquilino_nome": "João Pereira", "imovel_identificacao": "Apto 305"}
    EXTRAIDO = ComprovanteExtraido(valor_identificado=2200.0, data_identificada="2026-07-15", legivel=True)

    def _client_fake(self, charges_abertas: list, updates: list) -> MagicMock:
        client = MagicMock()

        def _rpc(nome, params):
            builder = MagicMock()
            if nome == "agent_update_charge_status":
                updates.append(params)
                builder.execute.return_value = MagicMock(data=None)
            else:
                raise AssertionError(f"RPC não mockada neste teste: {nome}")
            return builder

        client.rpc.side_effect = _rpc
        client.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(
            data=charges_abertas
        )
        return client

    def test_caso_a_falha_ao_notificar_nao_apaga_o_update_ja_feito(self):
        charges_abertas = [{"id": "charge-unica", "tipo": "aluguel", "valor_esperado": 2200.0}]
        updates: list = []
        client_fake = self._client_fake(charges_abertas, updates)

        with patch(
            "app.agents.a2_cobranca.comprovante.notificar_fernanda_comprovante",
            side_effect=RuntimeError("Meta fora do ar"),
        ):
            _resolver_charge_e_notificar(
                client_fake, self.CONTRACT_ID, self.EXTRAIDO, self.DADOS_CONTRATO
            )  # não deve levantar

        assert len(updates) == 1
        assert updates[0]["p_charge_id"] == "charge-unica"
        assert updates[0]["p_status"] == "aguardando_confirmacao"

    def test_caso_ba_falha_ao_notificar_nao_apaga_o_update_ja_feito(self):
        charges_abertas = [
            {"id": "charge-aluguel", "tipo": "aluguel", "valor_esperado": 2200.0},
            {"id": "charge-agua", "tipo": "agua", "valor_esperado": 95.0},
        ]
        updates: list = []
        client_fake = self._client_fake(charges_abertas, updates)

        with patch(
            "app.agents.a2_cobranca.comprovante.notificar_fernanda_comprovante",
            side_effect=RuntimeError("Meta fora do ar"),
        ):
            _resolver_charge_e_notificar(
                client_fake, self.CONTRACT_ID, self.EXTRAIDO, self.DADOS_CONTRATO
            )  # não deve levantar

        assert len(updates) == 1
        assert updates[0]["p_charge_id"] == "charge-aluguel"
        assert updates[0]["p_status"] == "aguardando_confirmacao"

    def test_caso_bb_falha_ao_notificar_nao_apaga_os_updates_ja_feitos(self):
        charges_abertas = [
            {"id": "charge-aluguel", "tipo": "aluguel", "valor_esperado": 2200.0},
            {"id": "charge-agua", "tipo": "agua", "valor_esperado": 100.0},
        ]
        extraido_soma = ComprovanteExtraido(
            valor_identificado=2300.0, data_identificada="2026-07-17", legivel=True
        )
        updates: list = []
        client_fake = self._client_fake(charges_abertas, updates)

        with patch(
            "app.agents.a2_cobranca.comprovante.notificar_fernanda_pagamento_combinado",
            side_effect=RuntimeError("Meta fora do ar"),
        ):
            _resolver_charge_e_notificar(
                client_fake, self.CONTRACT_ID, extraido_soma, self.DADOS_CONTRATO
            )  # não deve levantar

        assert len(updates) == 2
        assert {u["p_charge_id"] for u in updates} == {"charge-aluguel", "charge-agua"}
        assert all(u["p_status"] == "aguardando_confirmacao" for u in updates)

    def test_sucesso_ao_notificar_continua_funcionando_normalmente(self):
        """Regressão de compatibilidade: sem falha nenhuma, o comportamento
        continua o mesmo de antes — update gravado e notificação chamada."""
        charges_abertas = [{"id": "charge-unica", "tipo": "aluguel", "valor_esperado": 2200.0}]
        updates: list = []
        client_fake = self._client_fake(charges_abertas, updates)
        chamadas_notificacao: list = []

        with patch(
            "app.agents.a2_cobranca.comprovante.notificar_fernanda_comprovante",
            side_effect=lambda *a, **k: chamadas_notificacao.append((a, k)),
        ):
            _resolver_charge_e_notificar(
                client_fake, self.CONTRACT_ID, self.EXTRAIDO, self.DADOS_CONTRATO
            )

        assert len(updates) == 1
        assert len(chamadas_notificacao) == 1
