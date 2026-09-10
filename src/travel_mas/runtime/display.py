"""Formatação em texto do que uma execução deixou: trajetória e tabelas do banco."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from .workspace import ToolCall


def format_trace(trace: Iterable[ToolCall], numbered: bool = True) -> str:
    """Trajetória em uma linha por chamada."""
    lines = []
    for index, call in enumerate(trace, 1):
        args = json.dumps(dict(call.args), ensure_ascii=False, default=str)
        prefix = f"{index:>3}. " if numbered else "  "
        lines.append(f"{prefix}{call.name}({args})")
    return "\n".join(lines) or "  (nenhuma ferramenta foi executada)"


def format_rows(rows: Sequence[dict[str, Any]], empty: str = "  (tabela vazia)") -> str:
    """Linhas de uma tabela do banco em colunas alinhadas."""
    if not rows:
        return empty
    columns = list(rows[0])
    widths = {
        col: max(len(col), *(len(str(row.get(col, ""))) for row in rows)) for col in columns
    }
    header = "  " + "  ".join(col.ljust(widths[col]) for col in columns)
    rule = "  " + "  ".join("-" * widths[col] for col in columns)
    body = [
        "  " + "  ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns)
        for row in rows
    ]
    return "\n".join([header, rule, *body])
