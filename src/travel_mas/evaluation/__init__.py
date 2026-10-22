"""Avaliação do sistema multiagente e comparação de configurações.

`casos`, `checks`, `suite` e `validation` avaliam os casos C01–C14, C07B e C12P, calculam
`pass^k` e montam a matriz de referência, defeitos e controles. `compare` roda os cenários por
modelo e topologia e reduz cada execução a tempo, número de chamadas de ferramenta, número de
chamadas ao modelo e hash do estado final do banco. Nenhum agente importa este pacote.
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
