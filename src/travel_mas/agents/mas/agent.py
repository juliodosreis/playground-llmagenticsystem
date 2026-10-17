"""Construtor ReAct com histórico privado e saída validada pelo contrato do papel."""

import json
from typing import Annotated, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from ...runtime import Context, with_transient_retry
from ...runtime.structured import estruturado, preencher
from ...runtime.workspace import chamada_atual


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    passos: int
    saida: dict


def build_agent(
    model: BaseChatModel,
    tools: list[BaseTool],
    prompt: str,
    esquema: type[BaseModel],
    context: Context,
):
    """Cada compilação fecha somente sobre o prompt e as ferramentas daquele papel."""
    ligado = model.bind_tools(tools) if tools else model
    ligado = with_transient_retry(ligado, context.retry_attempts)
    saida = estruturado(model, esquema, context.retry_attempts)
    por_nome = {tool.name: tool for tool in tools}

    async def pensar(state: AgentState):
        resposta = await ligado.ainvoke([SystemMessage(prompt), *state["messages"]])
        return {"messages": [resposta], "passos": state.get("passos", 0) + 1}

    async def executar(state: AgentState):
        observacoes = []
        for chamada in state["messages"][-1].tool_calls:
            token = chamada_atual.set(chamada["id"])
            try:
                ferramenta = por_nome[chamada["name"]]
                observacao = await ferramenta.ainvoke(chamada)
            except Exception as exc:
                observacao = ToolMessage(
                    content=f"Erro de ferramenta: {type(exc).__name__}: {exc}",
                    tool_call_id=chamada["id"],
                    name=chamada["name"],
                    status="error",
                )
            finally:
                chamada_atual.reset(token)
            # Alguns provedores omitem tool_call_id no transporte para o modelo.
            # A referência de evidência precisa aparecer no conteúdo observável.
            try:
                payload = json.loads(observacao.content)
            except (ValueError, TypeError):
                payload = observacao.content
            observacao = observacao.model_copy(
                update={
                    "content": json.dumps(
                        {
                            "evidencia": chamada["id"],
                            "resultado": payload,
                        },
                        ensure_ascii=False,
                    )
                }
            )
            observacoes.append(observacao)
        return {"messages": observacoes}

    async def concluir(state: AgentState):
        resultado = await preencher(saida, [SystemMessage(prompt), *state["messages"]], esquema)
        dados = resultado.model_dump(mode="json")
        # A saída tipada entra no histórico privado, que a ativação seguinte do papel recebe.
        return {
            "saida": dados,
            "passos": state.get("passos", 0) + 1,
            "messages": [AIMessage(json.dumps(dados, ensure_ascii=False))],
        }

    def continuar(state: AgentState):
        if getattr(state["messages"][-1], "tool_calls", None):
            if state["passos"] >= context.max_steps:
                raise RuntimeError("o agente atingiu max_steps com chamadas pendentes")
            return "executar"
        return "concluir"

    builder = StateGraph(AgentState)
    builder.add_node("pensar", pensar)
    builder.add_node("executar", executar)
    builder.add_node("concluir", concluir)
    builder.add_edge(START, "pensar" if tools else "concluir")
    builder.add_conditional_edges("pensar", continuar, ["executar", "concluir"])
    builder.add_edge("executar", "pensar")
    builder.add_edge("concluir", END)
    return builder.compile()
