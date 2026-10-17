"""Orquestração sobre bandejas tipadas; os históricos pertencem aos subgrafos."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Literal, TypedDict
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import ValidationError

from ...runtime import Context, Workspace, load_chat_model
from ...runtime.workspace import agente_atual
from ...tools import build_toolbox
from .contracts import (
    TRANSFERENCIAS,
    Decisao,
    Ordem,
    Pedido,
    Proposta,
    Relatorio,
    ResultadoPesquisa,
    ResultadoVerificacao,
    Veredito,
)
from .coordenador.graph import build_graph as coordenador
from .defects import aprovacao_automatica, reserva_sem_veredito
from .pesquisador.graph import build_graph as pesquisador
from .reservador.graph import build_graph as reservador
from .verificador.graph import build_graph as verificador

AGENTES = {
    "coordenador": coordenador,
    "pesquisador": pesquisador,
    "verificador": verificador,
    "reservador": reservador,
}
TOPOLOGIAS = ("workflow", "supervisor")


class MASState(TypedDict):
    pedido_usuario: str
    tarefa_id: str
    bandejas: dict[str, list[dict]]
    bitacora: list[dict]
    rodada: int
    max_rodadas: int
    pesquisas: int
    motivo_terminacao: str
    final: str
    relatorio: dict
    passos: int
    proximo: str


def entregar(de, para, mensagem, *, state: MASState, workspace: Workspace):
    """Única fronteira de transferência: valida, registra e entrega cópia serializada."""
    tipo = type(mensagem).__name__
    if tipo not in TRANSFERENCIAS:
        raise TypeError(f"transferência desconhecida: {tipo}")
    if de not in AGENTES or para not in AGENTES:
        raise ValueError("remetente e destinatário devem ser agentes registrados")
    if (
        de == "coordenador"
        and tipo in ("Pedido", "Ordem")
        and workspace.defect("D4", aresta=f"{de}->{para}")
    ):
        mensagem = mensagem.model_copy(update={"user_id": None if tipo == "Pedido" else "u-outro"})
    conteudo = TRANSFERENCIAS[tipo].model_validate(mensagem).model_dump(mode="json")
    evento = workspace.emit("handoff", de=de, para=para, mensagem_tipo=tipo, conteudo=conteudo)
    recebido = workspace.intervir_mensagem(de, para, tipo, conteudo)
    evento.update(entregue=recebido is not None, recebido=deepcopy(recebido))
    state["bitacora"].append(deepcopy(evento))
    if recebido is not None:
        state["bandejas"][para].append({"tipo": tipo, "conteudo": recebido})


def build_graph(workspace=None, context=None, model=None):
    """Compila quatro subgrafos privados sobre o mesmo ambiente de ferramentas."""
    workspace = workspace if workspace is not None else Workspace()
    context = context or Context()
    workspace.defeitos = context.defeitos
    model = model if model is not None else load_chat_model(context)
    toolbox = build_toolbox(workspace)
    agentes = {nome: montar(model, toolbox, context) for nome, montar in AGENTES.items()}
    # O encerramento é o Coordenador com o mesmo prompt e histórico, restrito ao Relatorio.
    encerramento = AGENTES["coordenador"](model, toolbox, context, esquema=Relatorio)
    # Históricos privados por tarefa_id e agente, fora do estado do pai. Cada ativação recebe o
    # histórico do papel e as mensagens da bandeja que chegaram depois da ativação anterior.
    historicos: dict[str, dict[str, dict]] = {}

    def enviar(state, de, para, mensagem):
        entregar(de, para, mensagem, state=state, workspace=workspace)

    def recebidas(state, agente, esquema):
        mensagens = []
        for envelope in state["bandejas"][agente]:
            if envelope["tipo"] == esquema.__name__:
                try:
                    mensagens.append(esquema.model_validate(envelope["conteudo"]))
                except ValidationError:
                    # O destinatário ainda vê a mensagem corrompida; o pai não a reconstrói.
                    pass
        return mensagens

    async def chamar(state, nome, esquema):
        # Só a bandeja do destinatário atravessa a fronteira do subgrafo, e só a parte nova.
        privado = historicos.setdefault(state["tarefa_id"], {}).setdefault(
            nome, {"messages": [], "lidas": 0}
        )
        bandeja = state["bandejas"][nome]
        novas = deepcopy(bandeja[privado["lidas"] :])
        lidas = len(bandeja)
        entrada = {"bandeja": novas}
        if nome == "coordenador":
            entrada.update(
                pedido_usuario=state["pedido_usuario"],
                tarefa_id=state["tarefa_id"],
                motivo_terminacao=state["motivo_terminacao"],
                topologia=context.topologia,
            )
        state["rodada"] += 1
        workspace.emit("agent_start", agente=nome, rodada=state["rodada"])
        token = agente_atual.set(nome)
        try:
            if nome == "verificador" and workspace.defect("D1", agente=nome):
                saida = aprovacao_automatica(novas)
            elif nome == "reservador" and "D3" in workspace._ativadas:
                saida = reserva_sem_veredito(workspace, novas, state["tarefa_id"])
            else:
                grafo = encerramento if nome == "coordenador" and esquema is Relatorio else None
                mensagens = [
                    *privado["messages"],
                    HumanMessage(json.dumps(entrada, ensure_ascii=False)),
                ]
                resultado = await (grafo or agentes[nome]).ainvoke(
                    {"messages": mensagens, "passos": 0},
                    {"recursion_limit": max(context.recursion_limit, 2 * context.max_steps + 3)},
                )
                saida = esquema.model_validate(resultado["saida"])
                state["passos"] += resultado["passos"]
                privado["messages"] = list(resultado.get("messages", mensagens))
            privado["lidas"] = lidas
            workspace.emit("agent_end", agente=nome, saida=saida.model_dump(mode="json"))
            return saida
        finally:
            agente_atual.reset(token)

    def finalizar(state, relatorio, motivo):
        state["motivo_terminacao"] = motivo
        state["relatorio"] = relatorio.model_dump(mode="json")
        state["final"] = relatorio.mensagem
        workspace.emit("termination", agente="coordenador", motivo=motivo)
        historicos.pop(state["tarefa_id"], None)
        return state, END

    async def coordenar(state):
        if state["rodada"] >= state["max_rodadas"] - 1 and "D6" not in workspace._ativadas:
            state["motivo_terminacao"] = state["motivo_terminacao"] or "max_rodadas"
        if state["motivo_terminacao"]:
            relatorio = await chamar(state, "coordenador", Relatorio)
            return finalizar(state, relatorio, state["motivo_terminacao"])
        decisao = await chamar(state, "coordenador", Decisao)
        if decisao.proximo == "fim":
            relatorio = decisao.relatorio
            if relatorio is None or not relatorio.mensagem:
                relatorio = Relatorio(
                    tarefa_id=state["tarefa_id"],
                    erros=["relatorio_ausente"],
                    mensagem="Execução encerrada: o Coordenador não forneceu um relatório.",
                )
            return finalizar(state, relatorio, "concluido")
        if decisao.proximo == "pesquisador":
            rejeicao = any(not v.aprovado for v in recebidas(state, "coordenador", Veredito))
            buscou = any(
                e["tipo"] == "tool_call" and e.get("agente") == "pesquisador"
                for e in workspace.eventos
            )
            # R10: a nova pesquisa responde a uma rejeição. Depois de um Relatorio sem opções
            # com busca executada, inclusive com erro de ferramenta, o passo seguinte é informar.
            # Sem busca executada, um Pedido corrigido conta como a nova pesquisa.
            if "D6" not in workspace._ativadas and (
                state["pesquisas"] >= 2 or (state["pesquisas"] >= 1 and buscou and not rejeicao)
            ):
                state["motivo_terminacao"] = "limite_repropostas"
                return state, "coordenador"
            if decisao.pedido is not None:
                enviar(state, "coordenador", "pesquisador", decisao.pedido)
                enviar(state, "coordenador", "verificador", decisao.pedido)
            elif not recebidas(state, "pesquisador", Pedido):
                raise ValueError("o Coordenador encaminhou pesquisa sem Pedido")
        elif decisao.proximo == "reservador":
            if not decisao.ordens:
                raise ValueError("o Coordenador encaminhou execução sem Ordem")
            for ordem in decisao.ordens:
                enviar(state, "coordenador", "reservador", ordem)
            # A Ordem segue com a Proposta e os Vereditos que referencia, cada um entregue uma
            # vez: uma Ordem de listar ou cancelar não reenvia a proposta de uma reserva antiga.
            ids = {o.proposta_id for o in decisao.ordens if o.proposta_id}
            todas = recebidas(state, "coordenador", Proposta)
            vereditos = recebidas(state, "coordenador", Veredito)
            rejeitadas = {v.proposta_id for v in vereditos if not v.aprovado}
            propostas = [p for p in todas if p.proposta_id in ids]
            antigas = [p for p in todas if p.proposta_id in rejeitadas]
            if ids and antigas and workspace.defect("D5", aresta="coordenador->reservador"):
                propostas = antigas[-1:]
            ids |= {p.proposta_id for p in propostas}
            entregues = [e["conteudo"] for e in state["bandejas"]["reservador"]]
            for mensagem in [*propostas, *(v for v in vereditos if v.proposta_id in ids)]:
                if mensagem.model_dump(mode="json") not in entregues:
                    enviar(state, "coordenador", "reservador", mensagem)
        elif context.topologia != "supervisor":
            raise ValueError("no workflow, a verificação sucede a pesquisa automaticamente")
        return state, decisao.proximo

    async def pesquisar(state):
        state["pesquisas"] += 1
        resultado = await chamar(state, "pesquisador", ResultadoPesquisa)
        if not resultado.propostas:
            if "D6" in workspace._ativadas:
                return state, "verificador"
            enviar(
                state,
                "pesquisador",
                "coordenador",
                Relatorio(
                    tarefa_id=state["tarefa_id"],
                    erros=[resultado.motivo or "sem_disponibilidade"],
                    mensagem=resultado.motivo,
                ),
            )
            return state, "coordenador"
        for proposta in resultado.propostas:
            enviar(state, "pesquisador", "verificador", proposta)
            enviar(state, "pesquisador", "coordenador", proposta)
        if workspace.defect("D2", aresta="pesquisador->coordenador"):
            for v in aprovacao_automatica(state["bandejas"]["verificador"]).vereditos:
                enviar(state, "pesquisador", "coordenador", v)
            return state, "coordenador"
        if "D6" in workspace._ativadas:
            return state, "verificador"
        return state, "verificador" if context.topologia == "workflow" else "coordenador"

    async def verificar(state):
        resultado = await chamar(state, "verificador", ResultadoVerificacao)
        if not resultado.vereditos:
            raise ValueError("verificação sem Veredito")
        rejeitados = [v for v in resultado.vereditos if not v.aprovado]
        for veredito in resultado.vereditos:
            enviar(state, "verificador", "coordenador", veredito)
        if rejeitados and workspace.defect("D3", agente="reservador"):
            pedidos = recebidas(state, "verificador", Pedido)
            if not pedidos or not pedidos[-1].user_id:
                raise ValueError("D3 sem usuário no Pedido")
            for v in rejeitados:
                enviar(
                    state,
                    "coordenador",
                    "reservador",
                    Ordem(
                        tarefa_id=v.tarefa_id,
                        proposta_id=v.proposta_id,
                        user_id=pedidos[-1].user_id,
                    ),
                )
                enviar(state, "verificador", "reservador", v)
                for p in recebidas(state, "verificador", Proposta):
                    if p.proposta_id == v.proposta_id:
                        enviar(state, "pesquisador", "reservador", p)
            return state, "reservador"
        if rejeitados:
            workspace.defect("D6", aresta="pesquisador->verificador")
        if rejeitados and (state["pesquisas"] < 2 or "D6" in workspace._ativadas):
            for veredito in rejeitados:
                enviar(state, "verificador", "pesquisador", veredito)
                for proposta in recebidas(state, "verificador", Proposta):
                    if proposta.proposta_id == veredito.proposta_id:
                        enviar(state, "verificador", "pesquisador", proposta)
            if context.topologia == "workflow" or "D6" in workspace._ativadas:
                return state, "pesquisador"
        return state, "coordenador"

    async def reservar(state):
        relatorio = await chamar(state, "reservador", Relatorio)
        enviar(state, "reservador", "coordenador", relatorio)
        return state, "coordenador"

    def iniciar(state):
        return {
            "tarefa_id": uuid4().hex,
            "bandejas": {nome: [] for nome in AGENTES},
            "bitacora": [],
            "rodada": 0,
            "max_rodadas": context.max_rodadas,
            "pesquisas": 0,
            "motivo_terminacao": "",
            "final": "",
            "relatorio": {},
            "passos": 0,
            "proximo": "coordenador",
        }

    def node(nome, func):
        async def executar(
            state: MASState,
        ) -> Command[Literal["coordenador", "pesquisador", "verificador", "reservador", "__end__"]]:
            state = deepcopy(state)
            if (
                nome != "coordenador"
                and state["rodada"] >= state["max_rodadas"] - 1
                and "D6" not in workspace._ativadas
            ):
                state["motivo_terminacao"] = "max_rodadas"
                state["proximo"] = "coordenador"
                return Command(goto="coordenador", update=state)
            try:
                state, destino = await func(state)
            except Exception as exc:
                erro = f"{type(exc).__name__}: {exc}"
                workspace.emit("error", agente=nome, erro=erro)
                relatorio = Relatorio(
                    tarefa_id=state["tarefa_id"],
                    erros=[erro],
                    mensagem=f"Falha na execução: {erro}",
                )
                if nome == "coordenador":
                    state, destino = finalizar(state, relatorio, "error")
                else:
                    enviar(state, nome, "coordenador", relatorio)
                    state["motivo_terminacao"] = "error"
                    destino = "coordenador"
            state["proximo"] = destino
            return Command(goto=destino, update=state)

        return executar

    def workflow_node(executar):
        async def atualizar(state):
            command = await executar(state)
            return command.update

        return atualizar

    builder = StateGraph(MASState)
    builder.add_node("iniciar", iniciar)
    for nome, func in {
        "coordenador": coordenar,
        "pesquisador": pesquisar,
        "verificador": verificar,
        "reservador": reservar,
    }.items():
        executar = node(nome, func)
        builder.add_node(
            nome, workflow_node(executar) if context.topologia == "workflow" else executar
        )
        if context.topologia == "workflow":
            if nome == "reservador":
                builder.add_edge(nome, "coordenador")
            else:
                destinos = {
                    "coordenador": ["coordenador", "pesquisador", "reservador", END],
                    "pesquisador": ["coordenador", "verificador"],
                    "verificador": ["coordenador", "pesquisador", "reservador"],
                }
                builder.add_conditional_edges(nome, lambda state: state["proximo"], destinos[nome])
    builder.add_edge(START, "iniciar")
    builder.add_edge("iniciar", "coordenador")
    return builder.compile(name=f"travel-mas-{context.topologia}")


async def abuild_graph(workspace=None, context=None, model=None):
    return await asyncio.to_thread(build_graph, workspace, context, model)


async def make_graph():
    """Studio: ambiente novo a cada execução."""
    return await abuild_graph()
