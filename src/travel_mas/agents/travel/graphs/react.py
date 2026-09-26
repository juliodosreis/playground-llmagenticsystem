"""Estratégia ReAct: o laço de ferramentas escrito como grafo do LangGraph.

    START -> chamar_modelo -> decidir_proximo_no
                                 |-- há pedidos e passos < limite -> executar_ferramentas
                                 |                                        |
                                 |                                        +-> chamar_modelo
                                 +-- caso contrário --------------------------> END

`chamar_modelo` acrescenta o prompt de sistema ao histórico e chama o modelo com as ferramentas
ligadas. `executar_ferramentas` roda os pedidos da última mensagem e devolve uma `ToolMessage` por
pedido. A rota lê a última mensagem e o contador de passos.

O contador vale por pedido: `chamar_modelo` o recomeça quando a última mensagem é do usuário. Numa
thread com checkpointer, como a do Studio, o estado de um pedido passa ao seguinte, e o contador
acumulado cortaria o laço depois de alguns pedidos.

O nó de ferramentas é um `ToolNode`, que devolve o erro da ferramenta como `ToolMessage`. A falha
entra no histórico e o modelo a recebe na chamada seguinte.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from ....runtime import Context, with_transient_retry
from ..prompts import SYSTEM_PROMPT
from ..state import TravelState


def build_react_graph(
    model: BaseChatModel,
    tools: list[BaseTool],
    context: Context,
) -> CompiledStateGraph:
    """Compila o laço de ferramentas sobre o modelo e as ferramentas dados."""
    model_with_tools = with_transient_retry(model.bind_tools(tools), context.retry_attempts)
    limite = context.max_steps

    async def chamar_modelo(state: TravelState) -> dict:
        """Chama o modelo com o prompt de sistema e o histórico, e conta o passo do pedido."""
        historico = [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        resposta = await model_with_tools.ainvoke(historico)
        inicio_do_pedido = isinstance(state["messages"][-1], HumanMessage)
        anteriores = 0 if inicio_do_pedido else state.get("passos", 0)
        return {"messages": [resposta], "passos": anteriores + 1}

    def decidir_proximo_no(state: TravelState) -> Literal["executar", "fim"]:
        """Continua enquanto houver pedido de chamada e o limite de passos não for atingido."""
        ultima = state["messages"][-1]
        if getattr(ultima, "tool_calls", None) and state.get("passos", 0) < limite:
            return "executar"
        return "fim"

    builder = StateGraph(TravelState)
    builder.add_node("chamar_modelo", chamar_modelo)
    builder.add_node("executar_ferramentas", ToolNode(tools))

    builder.add_edge(START, "chamar_modelo")
    builder.add_conditional_edges(
        "chamar_modelo",
        decidir_proximo_no,
        {"executar": "executar_ferramentas", "fim": END},
    )
    builder.add_edge("executar_ferramentas", "chamar_modelo")

    return builder.compile(name="travel-agent")
