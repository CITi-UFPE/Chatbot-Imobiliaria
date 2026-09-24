"""Job diário do A2 (app/jobs/cron_cobranca_diaria.py): a geração de
charges de aluguel roda antes da cobrança, e uma falha nela não impede a
cobrança do dia."""

from unittest.mock import patch

from app.jobs import cron_cobranca_diaria


def test_gera_charges_antes_de_executar_cobranca():
    ordem: list = []
    with patch(
        "app.agents.a2_cobranca.gerar_charges_aluguel", side_effect=lambda: ordem.append("gerar")
    ), patch(
        "app.agents.a2_cobranca.executar_cobranca_diaria", side_effect=lambda: ordem.append("cobrar")
    ):
        assert cron_cobranca_diaria.main() == 0

    assert ordem == ["gerar", "cobrar"]


def test_falha_na_geracao_nao_impede_cobranca_do_dia():
    with patch(
        "app.agents.a2_cobranca.gerar_charges_aluguel", side_effect=RuntimeError("supabase fora")
    ), patch("app.agents.a2_cobranca.executar_cobranca_diaria") as cobrar:
        assert cron_cobranca_diaria.main() == 0

    cobrar.assert_called_once_with()
