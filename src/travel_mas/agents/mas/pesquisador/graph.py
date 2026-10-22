"""Subgrafo privado do pesquisador."""

from ..agent import build_agent
from ..contracts import ResultadoPesquisa
from .prompts import SYSTEM_PROMPT

TOOL_NAMES = ("search_flights", "search_hotels")


def build_graph(model, toolbox, context):
    return build_agent(
        model, toolbox.select(*TOOL_NAMES), SYSTEM_PROMPT, ResultadoPesquisa, context
    )
