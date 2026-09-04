"""Testes de roteamento do orquestrador (app/orchestrator/orchestrator.py).

Nenhum teste aqui chama Anthropic/Supabase de verdade — classificar_intencao,
avaliar_escalonamento, executar_escalonamento e responder_inquilino são
monkeypatchados no módulo app.orchestrator.orchestrator (importados por
nome direto ali, então sobrescrever o atributo do módulo é suficiente)."""

from app.orchestrator import orchestrator as orch
from app.orchestrator.classificador import ClassificacaoIntencao


def _classificacao(agente: str) -> ClassificacaoIntencao:
    return ClassificacaoIntencao(agente=agente, motivo="teste", urgencia="baixa")


class TestRotearParaForaDeEscopo:
    """Conteúdo com algo além de saudação, mas sem relação nenhuma com o
    contrato (papo aleatório com conteúdo, outro imóvel etc.) recebe
    recusa direta — nunca chama A1 nem A5, nunca implica que algo foi
    registrado/escalado."""

    def test_recusa_direta_sem_chamar_a1_nem_a5(self, monkeypatch):
        monkeypatch.setattr(orch, "classificar_intencao", lambda texto, hist: _classificacao("FORA_DE_ESCOPO"))

        chamou_a1 = []
        chamou_a5 = []
        monkeypatch.setattr(orch, "responder_inquilino", lambda *a: chamou_a1.append(a) or "não devia rodar")
        monkeypatch.setattr(orch, "avaliar_escalonamento", lambda *a: chamou_a5.append(a) or None)

        resposta, agente = orch.rotear_mensagem("contract-1", "kkkk que time ganhou ontem?")

        assert agente is None
        assert chamou_a1 == []
        assert chamou_a5 == []  # nem chega a avaliar escalonamento — decidido já na classificação
        assert resposta  # não vazio

    def test_recusa_nunca_promete_registro_ou_retorno_da_equipe(self, monkeypatch):
        """A regra central desta revisão do plano (ver Global Constraints):
        frases como 'já deixei registrado' ou 'equipe entra em contato' só
        podem aparecer quando executar_escalonamento de fato rodou — o que
        não é o caso aqui."""
        monkeypatch.setattr(orch, "classificar_intencao", lambda texto, hist: _classificacao("FORA_DE_ESCOPO"))

        resposta, _ = orch.rotear_mensagem("contract-1", "vocês têm apartamento pra alugar no bairro X?")

        proibidas = ("registrado", "encaminhei", "encaminhar", "entra em contato", "protocolo")
        texto_lower = resposta.lower()
        for termo in proibidas:
            assert termo not in texto_lower, f"resposta de recusa não pode conter {termo!r}: {resposta!r}"


class TestRotearParaA1IncluiSaudacao:
    """Saudação pura não tem branch próprio no orquestrador (ver Task 1/2
    do plano de correção) — cai no mesmo caminho de qualquer outra
    mensagem classificada como A1, e é o A1 quem gera a resposta cordial."""

    def test_classificado_como_a1_chama_responder_inquilino_normalmente(self, monkeypatch):
        monkeypatch.setattr(orch, "classificar_intencao", lambda texto, hist: _classificacao("A1"))
        monkeypatch.setattr(
            orch, "responder_inquilino", lambda cid, texto, hist: "Oi! Tudo bem sim, e você?"
        )

        resposta, agente = orch.rotear_mensagem("contract-1", "oi, tudo bem?")

        assert resposta == "Oi! Tudo bem sim, e você?"
        assert agente == "A1"


class TestRotearParaA5SemCriterio:
    """Quando o classificador manda a mensagem pro A5 (achou que era caso
    de risco/decisão humana) mas avaliar_escalonamento decide que não há
    motivo objetivo pra escalar, a resposta não pode mais ser o texto
    genérico fixo — precisa delegar pro A1 (que tenta responder de
    verdade, com acesso aos dados do contrato). Diferente de
    FORA_DE_ESCOPO: aqui o classificador julgou que HAVIA relação com o
    contrato, só não achou motivo de escalar — vale a pena o A1 tentar."""

    def test_sem_criterio_delega_para_a1_e_reporta_agente_a1(self, monkeypatch):
        monkeypatch.setattr(orch, "classificar_intencao", lambda texto, hist: _classificacao("A5"))
        monkeypatch.setattr(orch, "avaliar_escalonamento", lambda texto, hist: None)
        monkeypatch.setattr(
            orch, "responder_inquilino", lambda cid, texto, hist: "Resposta real do A1 sobre o contrato."
        )

        resposta, agente = orch.rotear_mensagem("contract-1", "isso é meio ambíguo mas fala do meu aluguel")

        assert resposta == "Resposta real do A1 sobre o contrato."
        assert agente == "A1"

    def test_texto_generico_antigo_nunca_mais_aparece(self, monkeypatch):
        """Regressão explícita do bug relatado: a string fixa não pode mais
        ser alcançável por nenhum caminho de rotear_mensagem."""
        monkeypatch.setattr(orch, "classificar_intencao", lambda texto, hist: _classificacao("A5"))
        monkeypatch.setattr(orch, "avaliar_escalonamento", lambda texto, hist: None)
        monkeypatch.setattr(orch, "responder_inquilino", lambda cid, texto, hist: "Qualquer resposta do A1.")

        resposta, _ = orch.rotear_mensagem("contract-1", "mensagem qualquer")

        assert "Já deixei registrado por aqui" not in resposta
        assert not hasattr(orch, "_RESPOSTA_A5_SEM_CRITERIO")

    def test_excecao_em_avaliar_escalonamento_tambem_delega_para_a1(self, monkeypatch):
        """Mesmo comportamento quando avaliar_escalonamento levanta (ex: falha
        de rede na chamada à Anthropic) — hoje isso já cai em avaliacao=None
        dentro de _rotear_para_a5, então o destino final é o mesmo do teste
        acima."""
        monkeypatch.setattr(orch, "classificar_intencao", lambda texto, hist: _classificacao("A5"))

        def _avaliar_com_falha(texto, hist):
            raise RuntimeError("Anthropic fora do ar")

        monkeypatch.setattr(orch, "avaliar_escalonamento", _avaliar_com_falha)
        monkeypatch.setattr(orch, "responder_inquilino", lambda cid, texto, hist: "Resposta do A1 mesmo assim.")

        resposta, agente = orch.rotear_mensagem("contract-1", "mensagem qualquer")

        assert resposta == "Resposta do A1 mesmo assim."
        assert agente == "A1"


class TestRotearParaA5ComCriterio:
    """Regressão: quando avaliar_escalonamento de fato encontra um critério,
    o comportamento de escalonamento real não pode mudar."""

    def test_com_criterio_continua_escalando_de_verdade(self, monkeypatch):
        from app.agents.a5_escalonamento import AvaliacaoEscalonamento

        avaliacao = AvaliacaoEscalonamento(
            motivo="pedido_humano",
            descricao="Inquilino pediu para falar com alguém da equipe.",
            resposta_para_inquilino="Já encaminhei seu caso para a equipe.",
        )
        monkeypatch.setattr(orch, "classificar_intencao", lambda texto, hist: _classificacao("A5"))
        monkeypatch.setattr(orch, "avaliar_escalonamento", lambda texto, hist: avaliacao)
        monkeypatch.setattr(orch, "executar_escalonamento", lambda cid, av: "ESC-2026-00001")

        chamou_a1 = []
        monkeypatch.setattr(orch, "responder_inquilino", lambda *a: chamou_a1.append(a) or "não devia ser chamado")

        resposta, agente = orch.rotear_mensagem("contract-1", "quero falar com o Domingos")

        assert resposta == "Já encaminhei seu caso para a equipe. (protocolo ESC-2026-00001)"
        assert agente == "A5"
        assert chamou_a1 == []  # não delega pro A1 quando de fato escalou
