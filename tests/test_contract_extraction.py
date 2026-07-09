from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.tools.contract_extraction import _extrair_payload, extrair_dados_contrato


def _payload_valido():
    return {
        "contrato": {
            "imovel_identificacao": "Apto 101",
            "imovel_endereco": "Rua X, 123",
            "tipo_locatario": "pf",
            "inquilino_nome": "Fulano de Tal",
            "inquilino_cpf_cnpj": "000.000.000-00",
            "garantia_tipo": "fiador",
            "fiador_nome": "Ciclano",
            "fiador_cpf": "111.111.111-11",
            "valor_aluguel": 2500.0,
            "dia_vencimento": 10,
            "data_inicio": "2026-01-01",
            "data_termino": "2027-01-01",
            "multa_infracao_tipo": "meses_aluguel",
            "multa_infracao_valor": 3,
            "aviso_previo_dias": 30,
            "aviso_previo_a_partir_mes": 1,
        },
        "clausulas": [
            {
                "numero_clausula": "1",
                "titulo_clausula": "Objeto",
                "texto_clausula": "texto...",
                "categoria": "financeiro",
            }
        ],
    }


def _resposta_com_tool_use(entrada: dict, stop_reason: str = "tool_use"):
    bloco = SimpleNamespace(type="tool_use", input=entrada)
    return SimpleNamespace(stop_reason=stop_reason, stop_details=None, content=[bloco])


def _mock_stream(resposta):
    """extrair_dados_contrato usa client.messages.stream(...) como context manager
    (necessário por causa de MAX_TOKENS=32000); mocka esse contrato."""
    context_manager = MagicMock()
    context_manager.__enter__.return_value.get_final_message.return_value = resposta
    return context_manager


class TestExtrairPayload:
    def test_formato_correto_direto(self):
        bruto = _payload_valido()
        assert _extrair_payload(bruto) is bruto

    def test_desembrulha_chave_extra(self):
        payload = _payload_valido()
        bruto = {"dados": payload}
        assert _extrair_payload(bruto) is payload

    def test_levanta_erro_sem_contrato_em_lugar_nenhum(self):
        with pytest.raises(RuntimeError, match="Formato de resposta inesperado"):
            _extrair_payload({"algo": {"outra_coisa": 1}})


class TestExtrairDadosContrato:
    @patch("app.tools.contract_extraction.Path")
    @patch("app.tools.contract_extraction.anthropic.Anthropic")
    def test_sucesso_primeira_tentativa(self, mock_anthropic_cls, mock_path_cls):
        mock_path_cls.return_value.read_bytes.return_value = b"%PDF-fake"
        mock_client = MagicMock()
        mock_client.messages.stream.return_value = _mock_stream(_resposta_com_tool_use(_payload_valido()))
        mock_anthropic_cls.return_value = mock_client

        resultado = extrair_dados_contrato("qualquer.pdf")

        assert resultado.contrato.inquilino_nome == "Fulano de Tal"
        assert len(resultado.clausulas) == 1
        assert mock_client.messages.stream.call_count == 1

    @patch("app.tools.contract_extraction.Path")
    @patch("app.tools.contract_extraction.anthropic.Anthropic")
    def test_retry_quando_clausulas_vem_vazia(self, mock_anthropic_cls, mock_path_cls):
        mock_path_cls.return_value.read_bytes.return_value = b"%PDF-fake"
        payload_vazio = _payload_valido()
        payload_vazio["clausulas"] = []
        mock_client = MagicMock()
        mock_client.messages.stream.side_effect = [
            _mock_stream(_resposta_com_tool_use(payload_vazio)),
            _mock_stream(_resposta_com_tool_use(_payload_valido())),
        ]
        mock_anthropic_cls.return_value = mock_client

        resultado = extrair_dados_contrato("qualquer.pdf")

        assert len(resultado.clausulas) == 1
        assert mock_client.messages.stream.call_count == 2

    @patch("app.tools.contract_extraction.Path")
    @patch("app.tools.contract_extraction.anthropic.Anthropic")
    def test_erro_quando_clausulas_vazia_em_todas_tentativas(self, mock_anthropic_cls, mock_path_cls):
        mock_path_cls.return_value.read_bytes.return_value = b"%PDF-fake"
        payload_vazio = _payload_valido()
        payload_vazio["clausulas"] = []
        mock_client = MagicMock()
        mock_client.messages.stream.return_value = _mock_stream(_resposta_com_tool_use(payload_vazio))
        mock_anthropic_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="zero cláusulas"):
            extrair_dados_contrato("qualquer.pdf", max_tentativas=2)

        assert mock_client.messages.stream.call_count == 2

    @patch("app.tools.contract_extraction.Path")
    @patch("app.tools.contract_extraction.anthropic.Anthropic")
    def test_erro_em_refusal(self, mock_anthropic_cls, mock_path_cls):
        mock_path_cls.return_value.read_bytes.return_value = b"%PDF-fake"
        mock_client = MagicMock()
        mock_client.messages.stream.return_value = _mock_stream(
            SimpleNamespace(stop_reason="refusal", stop_details="motivo x", content=[])
        )
        mock_anthropic_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="recusou"):
            extrair_dados_contrato("qualquer.pdf")

    @patch("app.tools.contract_extraction.Path")
    @patch("app.tools.contract_extraction.anthropic.Anthropic")
    def test_erro_sem_tool_use(self, mock_anthropic_cls, mock_path_cls):
        mock_path_cls.return_value.read_bytes.return_value = b"%PDF-fake"
        mock_client = MagicMock()
        mock_client.messages.stream.return_value = _mock_stream(
            SimpleNamespace(stop_reason="end_turn", stop_details=None, content=[])
        )
        mock_anthropic_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="não retornou dados estruturados"):
            extrair_dados_contrato("qualquer.pdf")
