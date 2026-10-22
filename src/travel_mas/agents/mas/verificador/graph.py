"""Subgrafo privado do verificador."""

from ..agent import build_agent
from ..contracts import ResultadoVerificacao
from .prompts import SYSTEM_PROMPT

TOOL_NAMES = ("check_item",)


def build_graph(model, toolbox, context):
    return build_agent(
        model, toolbox.select(*TOOL_NAMES), SYSTEM_PROMPT, ResultadoVerificacao, context
    )
