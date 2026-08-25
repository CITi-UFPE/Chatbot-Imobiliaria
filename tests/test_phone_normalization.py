import pytest

from app.orchestrator.phone_normalization import gerar_candidatos_telefone_br


@pytest.mark.parametrize(
    "telefone",
    (
        "+55 (81) 99876-5432",
        "5581998765432",
        "81 99876-5432",
    ),
)
def test_gera_candidatos_para_movel_com_nono_digito(telefone: str) -> None:
    assert gerar_candidatos_telefone_br(telefone) == (
        "5581998765432",
        "558198765432",
    )


@pytest.mark.parametrize(
    "telefone",
    (
        "+55 (81) 9876-5432",
        "558198765432",
        "81 9876-5432",
    ),
)
def test_gera_candidatos_para_movel_sem_nono_digito(telefone: str) -> None:
    assert gerar_candidatos_telefone_br(telefone) == (
        "5581998765432",
        "558198765432",
    )


def test_telefone_fixo_nao_recebe_variante_movel() -> None:
    assert gerar_candidatos_telefone_br("+55 (81) 3456-7890") == ("558134567890",)


def test_remove_somente_o_nono_digito_depois_do_ddd() -> None:
    assert gerar_candidatos_telefone_br("+55 (81) 99999-9999") == (
        "5581999999999",
        "558199999999",
    )


def test_adiciona_codigo_do_pais_ao_numero_informado_sem_55() -> None:
    assert gerar_candidatos_telefone_br("81999999999") == (
        "5581999999999",
        "558199999999",
    )


@pytest.mark.parametrize(
    "telefone",
    (
        None,
        "",
        "   ",
        "819999",
        "55819999999999",
        "4481999999999",
        "081999999999",
        "5581912345678",
        "+55 81 99999-9999 ramal 2",
        "+55+81 99999-9999",
    ),
)
def test_rejeita_entrada_invalida_sem_levantar_excecao(telefone: object) -> None:
    assert gerar_candidatos_telefone_br(telefone) == ()


def test_telefone_invalido_nao_causa_excecao_no_webhook() -> None:
    from app.orchestrator.processar_mensagem import processar_mensagem_recebida

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "telefone inválido",
                                    "type": "text",
                                    "text": {"body": "Olá"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    assert processar_mensagem_recebida(payload) == (
        "Nenhum contrato ativo encontrado para o telefone telefone inválido."
    )
