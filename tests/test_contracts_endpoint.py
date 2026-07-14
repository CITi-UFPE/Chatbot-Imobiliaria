from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import app
from app.models.contract import ClausulaExtraida, ContratoExtraido, ExtracaoContratoResult

client = TestClient(app)


def _resultado_valido() -> ExtracaoContratoResult:
    return ExtracaoContratoResult(
        contrato=ContratoExtraido(
            imovel_identificacao="Apto 101",
            imovel_endereco="Rua X, 123",
            tipo_locatario="pf",
            inquilino_nome="Fulano de Tal",
            inquilino_cpf_cnpj="000.000.000-00",
            garantia_tipo="fiador",
            fiador_nome="Ciclano",
            fiador_cpf="111.111.111-11",
            valor_aluguel=2500.0,
            dia_vencimento=10,
            data_inicio="2026-01-01",
            data_termino="2027-01-01",
            multa_infracao_tipo="meses_aluguel",
            multa_infracao_valor=3,
            aviso_previo_dias=30,
            aviso_previo_a_partir_mes=1,
        ),
        clausulas=[
            ClausulaExtraida(
                numero_clausula="1",
                titulo_clausula="Objeto",
                texto_clausula="texto...",
                categoria="financeiro",
            )
        ],
    )


def _upload(content_type: str = "application/pdf", conteudo: bytes = b"%PDF-fake"):
    return client.post(
        "/contracts/extrair",
        files={"arquivo": ("contrato.pdf", conteudo, content_type)},
    )


class TestExtrairContratoEndpoint:
    @patch("app.api.routers.contracts.extrair_dados_contrato")
    def test_caminho_feliz(self, mock_extrair):
        mock_extrair.return_value = _resultado_valido()

        response = _upload()

        assert response.status_code == 200
        corpo = response.json()
        assert corpo["contrato"]["inquilino_nome"] == "Fulano de Tal"
        assert corpo["contrato"]["garantia_valor"] is None  # null explícito, não omitido
        assert len(corpo["clausulas"]) == 1
        assert corpo["clausulas"][0]["categoria"] == "financeiro"

    def test_content_type_nao_pdf_rejeitado(self):
        response = _upload(content_type="text/plain")

        assert response.status_code == 415

    @patch("app.api.routers.contracts.extrair_dados_contrato")
    def test_erro_de_extracao_vira_422(self, mock_extrair):
        mock_extrair.side_effect = RuntimeError("Claude recusou a extração")

        response = _upload()

        assert response.status_code == 422
        assert "Claude recusou a extração" in response.json()["detail"]

    @patch("app.api.routers.contracts.os.unlink")
    @patch("app.api.routers.contracts.extrair_dados_contrato")
    def test_arquivo_temporario_e_apagado_mesmo_com_falha(self, mock_extrair, mock_unlink):
        mock_extrair.side_effect = RuntimeError("zero cláusulas")

        _upload()

        mock_unlink.assert_called_once()
