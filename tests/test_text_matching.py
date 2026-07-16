from app.tools.text_matching import contem_palavra, normalizar


def test_normalizar_remove_acento_e_caixa():
    assert normalizar("GÁS, Fumaça, Incêndio") == "gas, fumaca, incendio"


def test_contem_palavra_casa_forma_acentuada():
    assert contem_palavra("Sinto cheiro de fumaça saindo da tomada", ("fumaca",))


def test_contem_palavra_nao_casa_substring_de_outra_palavra():
    assert not contem_palavra("Já gastei muito tentando consertar a torneira", ("gas",))
    assert not contem_palavra("compromisso", ("isso",))
    assert not contem_palavra("assim que puder te aviso", ("sim",))


def test_contem_palavra_casa_palavra_isolada():
    assert contem_palavra("Sim, é esse mesmo", ("sim",))
    assert contem_palavra("Isso mesmo, correto", ("isso",))
