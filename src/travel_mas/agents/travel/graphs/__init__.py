"""Estratégias do agente de viagens, uma topologia de grafo por módulo.

Cada montador recebe o modelo, as ferramentas e o contexto, e devolve o grafo compilado.
`STRATEGIES` indexa os montadores pelo nome que `Context.strategy` aceita.
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from ....runtime import Context
from .plan_execute import build_plan_execute_graph
from .react import build_react_graph

StrategyBuilder = Callable[[BaseChatModel, list[BaseTool], Context], CompiledStateGraph]

STRATEGIES: dict[str, StrategyBuilder] = {
    "react": build_react_graph,
    "plan-execute": build_plan_execute_graph,
}

__all__ = ["STRATEGIES", "StrategyBuilder", "build_plan_execute_graph", "build_react_graph"]
