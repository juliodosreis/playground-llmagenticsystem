"""Subgrafo privado do coordenador."""

from ..agent import build_agent
from ..contracts import Decisao
from .prompts import SYSTEM_PROMPT

TOOL_NAMES = ()


def build_graph(model, toolbox, context, esquema=Decisao):
    """`esquema=Relatorio` compila o encerramento, que admite só o relatório final."""
    return build_agent(model, toolbox.select(*TOOL_NAMES), SYSTEM_PROMPT, esquema, context)
