"""Normalização pura de telefones brasileiros usados no WhatsApp."""

from __future__ import annotations

import re

_CARACTERES_ACEITOS = re.compile(r"^\+?[0-9(). -]+$")


def gerar_candidatos_telefone_br(telefone: object) -> tuple[str, ...]:
    """Devolve formas equivalentes com país, sem caracteres de apresentação.

    Celulares geram a forma atual e a variante legada sem o nono dígito.
    Telefones fixos geram uma única forma. Entradas inválidas retornam uma
    tupla vazia; o helper não levanta exceções para dados vindos do webhook.
    """
    if not isinstance(telefone, str):
        return ()

    apresentado = telefone.strip()
    if not apresentado or not _CARACTERES_ACEITOS.fullmatch(apresentado):
        return ()

    digitos = re.sub(r"\D", "", apresentado)
    if len(digitos) in (12, 13):
        if not digitos.startswith("55"):
            return ()
        numero_nacional = digitos[2:]
    elif len(digitos) in (10, 11):
        numero_nacional = digitos
    else:
        return ()

    ddd = numero_nacional[:2]
    assinante = numero_nacional[2:]
    if len(ddd) != 2 or ddd[0] == "0":
        return ()

    prefixo = f"55{ddd}"
    if len(assinante) == 8:
        if assinante[0] in "2345":
            return (f"{prefixo}{assinante}",)
        if assinante[0] in "6789":
            return (f"{prefixo}9{assinante}", f"{prefixo}{assinante}")
        return ()

    if len(assinante) == 9 and assinante[0] == "9" and assinante[1] in "6789":
        return (f"{prefixo}{assinante}", f"{prefixo}{assinante[1:]}")

    return ()
