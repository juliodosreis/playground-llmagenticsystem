"""Relatório de uma comparação, em texto.

A tabela traz uma linha por cenário e uma coluna por modelo, com o tempo e o número de chamadas de
ferramenta. A coluna `estado` diz se os modelos terminaram com o mesmo hash de banco.
"""

from __future__ import annotations

from ..runtime import format_rows
from .compare import Comparison


def comparison_rows(comparison: Comparison) -> list[dict[str, str]]:
    """Uma linha por cenário, com uma coluna por modelo e a coluna do estado final."""
    rows = []
    for scenario in comparison.scenarios:
        row = {"cenário": f"{scenario.key}. {scenario.name}"}
        for run in scenario.runs:
            row[run.label] = run.cell()
        row["estado"] = "igual" if scenario.agree() else "difere"
        rows.append(row)
    return rows


def format_comparison(comparison: Comparison) -> str:
    """Tabela dos cenários seguida do total por modelo."""
    linhas = [format_rows(comparison_rows(comparison), empty="  (nenhum cenário)")]

    total = len(comparison.scenarios)
    linhas.append(f"\nESTADO FINAL IGUAL EM {comparison.agreed()} DE {total} CENÁRIOS")

    linhas.append("\nTOTAL POR MODELO")
    resumo = [
        {
            "modelo": label,
            "tempo": f"{comparison.total_seconds(label)}s",
            "erros": str(comparison.errors(label)),
        }
        for label in comparison.labels
    ]
    linhas.append(format_rows(resumo))

    divergentes = [s for s in comparison.scenarios if not s.agree()]
    if divergentes:
        linhas.append("\nCENÁRIOS COM ESTADO DIFERENTE")
        for scenario in divergentes:
            linhas.append(f"  {scenario.key}. {scenario.name}")
            for run in scenario.runs:
                marca = run.error or run.state or "(sem estado)"
                linhas.append(f"    {run.label}: {marca}")

    return "\n".join(linhas)
