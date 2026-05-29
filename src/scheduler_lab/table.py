"""
Renderização de tabela ASCII.

Receber cabeçalhos + linhas e devolver uma string já alinhada em colunas. Uso isso nos relatórios e nos logs do scheduler customizado quando preciso mostrar scores por worker.
"""

from __future__ import annotations

def render_table(headers, rows):
    # Converto tudo para string logo de cara, assim o cálculo de largura de coluna não precisa lidar com tipos diferentes (int, float, etc.).
    data = [[str(cell) for cell in row] for row in rows]

    # começo cada coluna com a largura do cabeçalho e vou aumentando sempre que aparecer uma célula maior nas linhas de dados
    widths = [len(str(header)) for header in headers]
    for row in data:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def line(values):
        # junto as células com dois espaços e completo cada uma até a largura final da coluna com ljust, pra ficar tudo alinhado.
        return "  ".join(str(value).ljust(widths[index]) for index, value in enumerate(values))

    # linha de traços que aparece entre o cabeçalho e os dados.
    separator = "  ".join("-" * width for width in widths)
    return "\n".join([line(headers), separator, *[line(row) for row in data]])
