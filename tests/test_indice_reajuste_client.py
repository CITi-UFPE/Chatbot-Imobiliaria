from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.tools.indice_reajuste_client import buscar_percentual_acumulado_12_meses


def _resposta_com_valores(valores: list[float]) -> MagicMock:
    mock_resposta = MagicMock()
    mock_resposta.raise_for_status.return_value = None
    mock_resposta.json.return_value = [{"data": "01/01/2024", "valor": str(v)} for v in valores]
    return mock_resposta


class TestBuscarPercentualAcumulado12Meses:
    @patch("app.tools.indice_reajuste_client.httpx.get")
    def test_calcula_acumulado_por_composicao_nao_soma_simples(self, mock_get):
        # 12 meses de 1% cada: soma simples daria 12%, composto dá um pouco mais.
        mock_get.return_value = _resposta_com_valores([1.0] * 12)

        resultado = buscar_percentual_acumulado_12_meses("igpm")

        assert resultado == pytest.approx(12.6825, abs=0.001)

    @patch("app.tools.indice_reajuste_client.httpx.get")
    def test_usa_apenas_os_ultimos_12_quando_api_devolve_13(self, mock_get):
        # 13º registro (o mais antigo) tem valor absurdo — não deve entrar na conta.
        mock_get.return_value = _resposta_com_valores([100.0] + [0.0] * 12)

        resultado = buscar_percentual_acumulado_12_meses("ipca")

        assert resultado == pytest.approx(0.0, abs=0.001)

    @patch("app.tools.indice_reajuste_client.httpx.get")
    def test_chama_codigo_de_serie_correto_por_indice(self, mock_get):
        mock_get.return_value = _resposta_com_valores([0.5] * 12)

        buscar_percentual_acumulado_12_meses("ipca")

        url_chamada = mock_get.call_args[0][0]
        assert "bcdata.sgs.433" in url_chamada

    @patch("app.tools.indice_reajuste_client.httpx.get")
    def test_erro_de_rede_vira_runtime_error_claro(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("falhou")

        with pytest.raises(RuntimeError, match="Falha ao buscar série"):
            buscar_percentual_acumulado_12_meses("igpm")

    @patch("app.tools.indice_reajuste_client.httpx.get")
    def test_poucos_registros_levanta_erro_claro(self, mock_get):
        mock_get.return_value = _resposta_com_valores([0.5] * 5)

        with pytest.raises(RuntimeError, match="12"):
            buscar_percentual_acumulado_12_meses("igpm")
