from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.tools.maintenance_classification import classificar_manutencao, gerar_pergunta_esclarecimento


def _classificacao_valida(**overrides):
    base = {
        "categoria": "hidraulica",
        "urgencia": "media",
        "sinais_risco": [],
        "justificativa": "Torneira pingando, sem risco.",
        "categoria_confidence": 0.95,
        "urgencia_confidence": 0.9,
    }
    base.update(overrides)
    return base


def _resposta_com_tool_use(entrada: dict, stop_reason: str = "tool_use"):
    bloco = SimpleNamespace(type="tool_use", input=entrada)
    return SimpleNamespace(stop_reason=stop_reason, content=[bloco])


def _resposta_com_texto(texto: str):
    bloco = SimpleNamespace(type="text", text=texto)
    return SimpleNamespace(stop_reason="end_turn", content=[bloco])


class TestClassificarManutencao:
    @patch("app.tools.maintenance_classification.anthropic.Anthropic")
    def test_classificacao_simples(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _resposta_com_tool_use(_classificacao_valida())
        mock_anthropic_cls.return_value = mock_client

        resultado = classificar_manutencao("A torneira da cozinha está pingando direto")

        assert resultado.categoria == "hidraulica"
        assert resultado.urgencia == "media"

    @patch("app.tools.maintenance_classification.anthropic.Anthropic")
    def test_forca_urgencia_alta_em_sinal_de_emergencia_ignorado_pelo_llm(self, mock_anthropic_cls):
        """Rede de segurança: mesmo se o LLM não sinalizar risco, palavras de
        emergência real (gás, fumaça, incêndio, choque) forçam urgencia=alta e
        registram o gatilho em sinais_risco (senão a notificação da gestora mostra
        'alta' ao lado de 'nenhum sinal de risco', sem explicação)."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _resposta_com_tool_use(
            _classificacao_valida(categoria="eletrica", urgencia="media", sinais_risco=[])
        )
        mock_anthropic_cls.return_value = mock_client

        resultado = classificar_manutencao("Sinto cheiro de fumaça saindo da tomada")

        assert resultado.urgencia == "alta"
        assert resultado.sinais_risco

    @patch("app.tools.maintenance_classification.anthropic.Anthropic")
    def test_nao_forca_urgencia_em_substring_coincidente(self, mock_anthropic_cls):
        """'gas' é substring de 'gastei'/'gastar' — não deve casar como palavra
        de emergência (regressão do bug de correspondência por substring)."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _resposta_com_tool_use(
            _classificacao_valida(urgencia="media")
        )
        mock_anthropic_cls.return_value = mock_client

        resultado = classificar_manutencao("Já gastei muito tentando consertar a torneira que pinga")

        assert resultado.urgencia == "media"
        assert resultado.sinais_risco == []

    @patch("app.tools.maintenance_classification.anthropic.Anthropic")
    def test_erro_em_refusal(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(stop_reason="refusal", content=[])
        mock_anthropic_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="recusou"):
            classificar_manutencao("qualquer relato")

    @patch("app.tools.maintenance_classification.anthropic.Anthropic")
    def test_erro_sem_tool_use(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(stop_reason="end_turn", content=[])
        mock_anthropic_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="não retornou uma classificação"):
            classificar_manutencao("qualquer relato")


class TestGerarPerguntaEsclarecimento:
    @patch("app.tools.maintenance_classification.anthropic.Anthropic")
    def test_gera_pergunta_a_partir_do_texto_retornado(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _resposta_com_texto(
            "Isso é a fiação/tomada com problema, ou tem água vazando perto da fiação?"
        )
        mock_anthropic_cls.return_value = mock_client

        classificacao = _classificacao_valida(categoria_confidence=0.4)
        from app.models.maintenance import ClassificacaoManutencao

        pergunta = gerar_pergunta_esclarecimento(
            "Tem um problema na fiação perto do chuveiro", ClassificacaoManutencao(**classificacao)
        )

        assert "fiação" in pergunta

    @patch("app.tools.maintenance_classification.anthropic.Anthropic")
    def test_erro_quando_resposta_vazia(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = SimpleNamespace(stop_reason="end_turn", content=[])
        mock_anthropic_cls.return_value = mock_client

        from app.models.maintenance import ClassificacaoManutencao

        with pytest.raises(RuntimeError, match="não retornou uma pergunta"):
            gerar_pergunta_esclarecimento("relato", ClassificacaoManutencao(**_classificacao_valida()))
