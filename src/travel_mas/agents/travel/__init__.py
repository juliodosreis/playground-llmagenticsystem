"""Agente de viagens: as seis ferramentas do sistema, sob uma de duas estratégias de grafo.

Quatro arquivos: `prompts.py` com os prompts, `tools.py` com as ferramentas declaradas, `state.py`
com o estado de cada estratégia e `graph.py` com a montagem. `graphs/` traz uma topologia por
estratégia, e `Context.strategy` escolhe entre elas.
"""

from .graph import build_graph, make_graph, make_plan_execute_graph
from .graphs import STRATEGIES
from .prompts import SYSTEM_PROMPT
from .state import PlanState, TravelState
from .tools import TOOL_NAMES, build_agent_tools

__all__ = [
    "STRATEGIES",
    "SYSTEM_PROMPT",
    "TOOL_NAMES",
    "PlanState",
    "TravelState",
    "build_agent_tools",
    "build_graph",
    "make_graph",
    "make_plan_execute_graph",
]
