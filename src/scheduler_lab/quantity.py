"""
Conversões de quantidades do Kubernetes.

O Kubernetes representa CPU em "millicores" (500m = 0,5 CPU, 2 = 2 CPUs) e
memória/disco com sufixos como Mi, Gi, Ki. Aqui eu transformo essas strings
em inteiros, porque o algoritmo de score precisa somar e comparar valores
limpos, sem ter que se preocupar com a unidade.

Uso Decimal e não float pra não perder precisão quando o YAML traz valores
como 1.5 ou 256Mi.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


# aqui temos a quantidade de bytes em um mebibyte (MiB)
MIB = 1024 * 1024


# aqui temos os sufixos de unidades binárias e decimais usados pelo Kubernetes, junto com seus multiplicadores correspondentes.

_BINARY_UNITS = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "Pi": 1024**5,
    "Ei": 1024**6,
}

_DECIMAL_UNITS = {
    "K": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
    "P": 1000**5,
    "E": 1000**6,
}


def parse_cpu_millicores(value):
    """Recebe uma quantidade de CPU do K8s e devolve o total em millicores."""
    # Trata None e string vazia como "sem pedido", assim n é necessário checar antes de chamar a função em todo lugar do código.
    if value is None: 
        return 0

    text = str(value).strip() # converte pra string e tira espaços em branco
    if not text:
        return 0

    # formato tipo "500m" já vem em millicores, é só tirar o "m" do final entao
    if text.endswith("m"):
        return int(Decimal(text[:-1]))

    # sem sufixo "m" o valor está em CPUs inteiras, então multiplico por 1000 pra converter para millicores.
    return int(Decimal(text) * 1000)


def format_cpu(millicores):
    # Mostra "2" quando der CPU inteira e "500m" quando for fração.
    # assim deixa os logs mais legíveis.
    if millicores % 1000 == 0:
        return f"{millicores // 1000}"
    return f"{millicores}m"


def parse_bytes(value):
    """Recebe uma quantidade de memória ou disco e devolve em bytes."""
    if value is None:
        return 0

    text = str(value).strip()
    if not text:
        return 0

    # tento juntar com algum sufixo conhecido (Mi, Gi, K, M, ...).
    # junto os dois dicionários pra percorrer numa única passada.
    for suffix, multiplier in {**_BINARY_UNITS, **_DECIMAL_UNITS}.items():
        if text.endswith(suffix):
            number = text[: -len(suffix)] # pega a parte numérica, tirando o sufixo do final
            return int(Decimal(number) * multiplier) 

    # Sem sufixo: o valor já está em bytes puros (ex.: "1024").
    try:
        return int(Decimal(text))
    except InvalidOperation as exc:
        raise ValueError(f"Quantidade Kubernetes invalida: {value!r}") from exc


def bytes_to_mib(value):
    # Arredondo pra evitar diferença de 1 byte quando o valor original
    # tinha sufixo decimal (ex.: 1M = 1.000.000 bytes != 1Mi).
    return int(round(value / MIB))


def parse_mib(value):
    # um atalho é o algoritmo compara espaços em MiB, então vale ter um helper que já entrega assim, em vez de chamar parse_bytes e dividir manualmente toda hora.
    return bytes_to_mib(parse_bytes(value))


def format_mib(value):
    return f"{value}Mi" # formata o valor em MiB de volta pra string, pra deixar os logs mais legíveis.
