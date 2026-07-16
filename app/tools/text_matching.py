import re
import unicodedata


def normalizar(texto: str) -> str:
    """minúsculas + sem acentos, para comparação por palavra-chave."""
    sem_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sem_acentos.lower()


def contem_palavra(texto: str, palavras: tuple[str, ...]) -> bool:
    """Checa palavra inteira (não substring) após normalizar acentos/caixa.

    Substring simples (ex: "gas" in "gastei") gera falsos positivos; \\b garante
    que só casa a palavra isolada.
    """
    texto_normalizado = normalizar(texto)
    return any(re.search(rf"\b{re.escape(palavra)}\b", texto_normalizado) for palavra in palavras)
