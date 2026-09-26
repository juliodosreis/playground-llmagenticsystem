"""Comparação de configurações sobre os cenários do pacote.

Roda os mesmos cenários por vários pares de modelo e estratégia, e reduz cada execução a tempo,
número de chamadas de ferramenta e hash do estado final do banco. Nenhum agente importa este
pacote.
"""

from .compare import (
    Comparison,
    ModelRun,
    ModelSpec,
    ScenarioComparison,
    SpecError,
    combine_specs,
    compare_models,
    parse_spec,
)
from .report import comparison_rows, format_comparison

__all__ = [
    "Comparison",
    "ModelRun",
    "ModelSpec",
    "ScenarioComparison",
    "SpecError",
    "combine_specs",
    "compare_models",
    "comparison_rows",
    "format_comparison",
    "parse_spec",
]
