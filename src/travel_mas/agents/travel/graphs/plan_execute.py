"""Estratégia Plan-and-Execute, com um desvio ao replanejador.

    START -> planejar -> seguir_plano
                           |-- passo pendente e passos < limite -> executar
                           +-- caso contrário -------------------> concluir -> END

    executar -> decidir
                  |-- desvio e ainda sem revisão -> replanejar -> seguir_plano
                  +-- caso contrário --------------> seguir_plano

`planejar` escreve a lista de passos antes de qualquer chamada de ferramenta. `executar` toma o
primeiro passo pendente, chama o modelo e roda o pedido da resposta, e o retorno da ferramenta vira
a evidência do passo. `concluir` escreve a mensagem final a partir do pedido e das evidências.

No esquema `Plano`, cada `Passo` tem o campo `ferramenta` e o campo `descricao`, e o estado guarda o
passo como o texto `ferramenta: descricao`. O prefixo libera uma ferramenta ao passo, segundo
`ferramenta_do_passo`, e o executor recebe só essa ferramenta ligada. Um prefixo fora das
ferramentas do agente não chama o modelo: o passo vira o erro `step_without_tool`, que desvia ao
replanejador.

O passo executa uma chamada. Um pedido a outra ferramenta volta como erro `tool_not_in_step`, e o
segundo pedido da mesma resposta volta como erro `one_call_per_step`, os dois sem executar. O
pedido recusado não passa pelo workspace e fica fora do trace, e `recusadas` o registra.

O desvio é determinístico: `exige_replano` marca a busca de catálogo que devolve lista vazia e o
retorno com o campo `error`, sem chamar o modelo. O replanejador troca os passos pendentes e mantém
os executados. O desvio é avaliado só depois de `executar`, e ocorre uma vez por pedido.

`passos` conta as chamadas ao modelo, como no laço ReAct. A rota deixa de mandar passos ao executor
e ao replanejador quando `passos` chega a `max_steps`, e `concluir` roda depois disso, com uma
chamada a mais.

O planejador e o replanejador preenchem o esquema pelo método `function_calling`, em que o esquema
é declarado como ferramenta, sobre a cópia do modelo que `without_reasoning` devolve. Quando a
resposta não traz essa chamada, ou traz campos fora do esquema, o parser devolve `None` ou levanta
exceção, e o pedido se repete até `TENTATIVAS_ESQUEMA` vezes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Literal

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field, ValidationError

from ....runtime import Context, with_transient_retry, without_reasoning
from ....tools import CATALOG_TOOLS
from ..prompts import EXECUTOR_PROMPT, SYNTHESIS_PROMPT, planner_prompt, replanner_prompt
from ..state import PlanState

TENTATIVAS_ESQUEMA = 3
"""Pedidos ao modelo antes de o planejador ou o replanejador desistir de preencher o esquema."""


class Passo(BaseModel):
    """Um passo do plano: a ferramenta que ele chama e o que obter com ela."""

    ferramenta: str = Field(description="Nome de uma das ferramentas do executor.")
    descricao: str = Field(
        description=(
            "Com quais dados chamar a ferramenta, e de qual passo anterior vem cada dado que "
            "depende de outro passo."
        )
    )

    def texto(self) -> str:
        return f"{self.ferramenta}: {self.descricao}"


class Plano(BaseModel):
    """Lista ordenada de passos para atender o pedido."""

    passos: list[Passo] = Field(description="Passos em ordem, uma chamada de ferramenta cada.")


class Replano(BaseModel):
    """Passos que ainda faltam, revistos depois das evidências coletadas."""

    passos_restantes: list[Passo] = Field(
        description="Passos que ainda precisam ser executados, em ordem."
    )


def exige_replano(ferramenta: str, retorno: str) -> bool:
    """Busca de catálogo sem resultado, ou retorno de qualquer ferramenta com o campo `error`."""
    if ferramenta in CATALOG_TOOLS and retorno.strip() == "[]":
        return True
    return '"error"' in retorno


def ferramenta_do_passo(passo: str, nomes: Sequence[str]) -> str | None:
    """O identificador no início do prefixo `ferramenta:`, quando nomeia uma das ferramentas.

    O identificador descarta o que vem depois do nome, e `search_flights():` libera
    `search_flights`. Um nome citado na descrição não libera a ferramenta.
    """
    prefixo, separador, _ = passo.partition(":")
    identificador = re.match(r"\s*([A-Za-z_]\w*)", prefixo)
    if separador and identificador and identificador.group(1) in nomes:
        return identificador.group(1)
    return None


def motivo_da_recusa(
    ferramenta: str,
    nomes: Sequence[str],
    liberada: str | None,
    excedente: bool,
) -> str | None:
    """O código de erro de um pedido que o passo não executa, ou `None` quando executa."""
    if ferramenta not in nomes:
        return "unknown_tool"
    if ferramenta != liberada:
        return "tool_not_in_step"
    if excedente:
        return "one_call_per_step"
    return None


def descrever_ferramentas(tools: Sequence[BaseTool]) -> str:
    """Uma linha por ferramenta, com nome, argumentos e descrição."""
    return "\n".join(
        f"- {tool.name}({', '.join(tool.args)}): {' '.join(tool.description.split())}"
        for tool in tools
    )


def descrever_pedido(messages: Sequence[AnyMessage]) -> str:
    """O pedido atual, precedido dos turnos anteriores da conversa quando houver.

    Um turno anterior é uma mensagem do usuário e a última mensagem do agente com texto antes da
    mensagem seguinte do usuário. Numa thread do Studio, o segundo pedido chega com o primeiro
    turno no histórico, e o planejador recebe os dois.
    """
    turnos: list[tuple[str, str]] = []
    usuario: str | None = None
    resposta = ""
    for message in messages:
        if isinstance(message, HumanMessage):
            if usuario is not None:
                turnos.append((usuario, resposta))
            usuario, resposta = message.text, ""
        elif isinstance(message, AIMessage) and message.text.strip():
            resposta = message.text.strip()

    atual = f"Pedido: {usuario or ''}"
    if not turnos:
        return atual
    anteriores = "\n".join(
        f"- usuário: {pergunta}\n- agente: {dada or '(sem resposta)'}"
        for pergunta, dada in turnos
    )
    return f"Conversa anterior:\n{anteriores}\n\n{atual}"


def formatar_evidencias(state: PlanState) -> str:
    """Cada passo executado seguido do que ele produziu, uma linha por par."""
    linhas = [
        f"- {passo}: {evidencia}"
        for passo, evidencia in zip(state["passos_feitos"], state["evidencias"], strict=True)
    ]
    return "\n".join(linhas) or "nenhum passo executado ainda"


async def preencher(estruturado: Runnable, mensagens: list[AnyMessage]) -> BaseModel:
    """Repete o pedido enquanto a resposta não trouxer o esquema preenchido."""
    for _ in range(TENTATIVAS_ESQUEMA):
        try:
            resultado = await estruturado.ainvoke(mensagens)
        except (OutputParserException, ValidationError):  # outra ferramenta, ou campo inválido
            continue
        if resultado is not None:
            return resultado
    raise RuntimeError(f"o modelo não preencheu o esquema em {TENTATIVAS_ESQUEMA} tentativas")


def build_plan_execute_graph(
    model: BaseChatModel,
    tools: list[BaseTool],
    context: Context,
) -> CompiledStateGraph:
    """Compila planejador, executor, replanejador e síntese sobre o modelo e as ferramentas."""
    tentativas = context.retry_attempts
    limite = context.max_steps
    ferramentas = descrever_ferramentas(tools)
    por_nome = {tool.name: tool for tool in tools}
    nomes = list(por_nome)

    sem_raciocinio = without_reasoning(model)

    def estruturado(esquema: type[BaseModel]) -> Runnable:
        saida = sem_raciocinio.with_structured_output(esquema, method="function_calling")
        return with_transient_retry(saida, tentativas)

    planejador = estruturado(Plano)
    replanejador = estruturado(Replano)
    executores = {
        tool.name: with_transient_retry(model.bind_tools([tool]), tentativas) for tool in tools
    }
    sem_ferramentas = with_transient_retry(model, tentativas)

    def mensagem_de_erro(chamada: ToolCall, erro: dict) -> ToolMessage:
        return ToolMessage(
            json.dumps(erro, ensure_ascii=False),
            name=chamada["name"],
            tool_call_id=chamada["id"],
            status="error",
        )

    async def chamar_ferramenta(chamada: ToolCall) -> ToolMessage:
        """Roda um pedido liberado. A exceção volta como `ToolMessage` com o campo `error`."""
        try:
            return await por_nome[chamada["name"]].ainvoke(chamada)
        except Exception as exc:  # argumento inválido: o erro vira evidência do passo
            return mensagem_de_erro(chamada, {"error": f"{type(exc).__name__}: {exc}"})

    async def planejar(state: PlanState) -> dict:
        """Escreve o plano e recomeça as listas e o contador do pedido."""
        plano = await preencher(
            planejador,
            [
                SystemMessage(planner_prompt(ferramentas)),
                HumanMessage(descrever_pedido(state["messages"])),
            ],
        )
        return {
            "plano": [passo.texto() for passo in plano.passos],
            "passos_feitos": [],
            "evidencias": [],
            "recusadas": [],
            "desvio": False,
            "replanejado": False,
            "passos": 1,
        }

    async def executar(state: PlanState) -> dict:
        """Executa o primeiro passo pendente e grava o que ele produziu."""
        passo = state["plano"][len(state["passos_feitos"])]
        liberada = ferramenta_do_passo(passo, nomes)
        if liberada is None:  # o plano nomeou algo que o agente não tem
            erro = json.dumps({"error": "step_without_tool", "step": passo}, ensure_ascii=False)
            return {
                "passos_feitos": [*state["passos_feitos"], passo],
                "evidencias": [*state["evidencias"], erro],
                "desvio": True,
            }

        resposta = await executores[liberada].ainvoke(
            [
                SystemMessage(EXECUTOR_PROMPT),
                HumanMessage(
                    f"{descrever_pedido(state['messages'])}\n\n"
                    f"Evidências:\n{formatar_evidencias(state)}\n\n"
                    f"Passo atual: {passo}"
                ),
            ]
        )
        observacoes: list[ToolMessage] = []
        recusadas: list[str] = []
        for indice, chamada in enumerate(resposta.tool_calls):
            motivo = motivo_da_recusa(chamada["name"], nomes, liberada, excedente=indice > 0)
            if motivo is None:
                observacoes.append(await chamar_ferramenta(chamada))
                continue
            erro = {"error": motivo, "tool": chamada["name"], "step_tool": liberada}
            observacoes.append(mensagem_de_erro(chamada, erro))
            argumentos = json.dumps(chamada["args"], ensure_ascii=False)
            recusadas.append(f"{chamada['name']}({argumentos}): {motivo}")
        evidencia = " ".join(str(obs.content) for obs in observacoes) or resposta.text
        return {
            "messages": [resposta, *observacoes],
            "passos": state["passos"] + 1,
            "passos_feitos": [*state["passos_feitos"], passo],
            "evidencias": [*state["evidencias"], evidencia],
            "recusadas": [*state["recusadas"], *recusadas],
            "desvio": any(exige_replano(obs.name or "", str(obs.content)) for obs in observacoes),
        }

    async def replanejar(state: PlanState) -> dict:
        """Troca os passos pendentes pelos que o modelo reescreveu."""
        feitos = state["passos_feitos"]
        pendentes = state["plano"][len(feitos) :]
        revisao = await preencher(
            replanejador,
            [
                SystemMessage(replanner_prompt(ferramentas)),
                HumanMessage(
                    f"{descrever_pedido(state['messages'])}\n\n"
                    f"Evidências:\n{formatar_evidencias(state)}\n\n"
                    "Passos pendentes:\n"
                    + ("\n".join(f"- {passo}" for passo in pendentes) or "nenhum")
                ),
            ],
        )
        return {
            "plano": [*feitos, *(passo.texto() for passo in revisao.passos_restantes)],
            "replanejado": True,
            "passos": state["passos"] + 1,
        }

    def seguir_plano(state: PlanState) -> Literal["executar", "concluir"]:
        """Executa o próximo passo enquanto houver pendente e o limite não for atingido."""
        if len(state["passos_feitos"]) < len(state["plano"]) and state["passos"] < limite:
            return "executar"
        return "concluir"

    def decidir(state: PlanState) -> Literal["replanejar", "executar", "concluir"]:
        """Desvia ao replanejador na primeira evidência de desvio, e segue o plano nos demais."""
        if state["desvio"] and not state["replanejado"] and state["passos"] < limite:
            return "replanejar"
        return seguir_plano(state)

    async def concluir(state: PlanState) -> dict:
        """Escreve a mensagem final a partir do pedido e das evidências."""
        resposta = await sem_ferramentas.ainvoke(
            [
                SystemMessage(SYNTHESIS_PROMPT),
                HumanMessage(
                    f"{descrever_pedido(state['messages'])}\n\n"
                    f"Evidências:\n{formatar_evidencias(state)}"
                ),
            ]
        )
        return {"messages": [resposta], "passos": state["passos"] + 1}

    builder = StateGraph(PlanState)
    builder.add_node("planejar", planejar)
    builder.add_node("executar", executar)
    builder.add_node("replanejar", replanejar)
    builder.add_node("concluir", concluir)

    builder.add_edge(START, "planejar")
    builder.add_conditional_edges("planejar", seguir_plano, ["executar", "concluir"])
    builder.add_conditional_edges("executar", decidir, ["replanejar", "executar", "concluir"])
    builder.add_conditional_edges("replanejar", seguir_plano, ["executar", "concluir"])
    builder.add_edge("concluir", END)

    return builder.compile(name="travel-agent-plan-execute")
