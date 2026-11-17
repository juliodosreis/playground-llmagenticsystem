"""Transporte A2A: adaptador do Agent Server, cliente JSON-RPC, agente cliente e CLI, sem rede."""

import asyncio
import base64
import importlib
import json
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from travel_mas import Context
from travel_mas.agents.mas.contracts import Decisao, Relatorio
from travel_mas.cli import main
from travel_mas.interfaces import a2a
from travel_mas.interfaces.a2a import cliente as cliente_a2a

from .test_mas import ModeloScriptado, entrada, script_reserva

UUID = "351c60ff-cc7e-5743-8921-54a06f8620da"
CARD = {
    "name": "travel_mas_a2a",
    "description": "Sistema multiagente de reservas de viagem.",
    "url": f"http://teste/a2a/{UUID}",
    "supportedInterfaces": [{"protocolBinding": "jsonrpc", "protocolVersion": "1.0"}],
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [{"id": f"{UUID}-main", "name": "travel_mas_a2a Capabilities"}],
}


def concluir(mensagem, pedidos=None):
    """Coordenador que encerra sem ferramentas e anota o pedido recebido."""

    def responder(messages):
        dados = entrada(messages)
        if pedidos is not None:
            pedidos.append(dados["pedido_usuario"])
        return Decisao(
            proximo="fim",
            relatorio=Relatorio(tarefa_id=dados["tarefa_id"], mensagem=mensagem),
        )

    return responder


def invocar(grafo, mensagens, thread_id=None):
    config = {"configurable": {"thread_id": thread_id}} if thread_id else {}
    return asyncio.run(grafo.ainvoke({"messages": mensagens}, config))


def arquivo_json(mensagem):
    bloco = next(b for b in mensagem.content if b["type"] == "file")
    assert (bloco["mime_type"], bloco["filename"]) == ("application/json", "relatorio.json")
    return json.loads(base64.b64decode(bloco["base64"]))


def test_adaptador_entrega_ultimo_texto_e_responde_texto_e_relatorio_json():
    pedidos = []
    model = ModeloScriptado(script=[concluir("Nenhuma reserva para u-31.", pedidos)])
    grafo = a2a.build_graph(Context(), model, ambientes={})
    final = invocar(
        grafo,
        [HumanMessage("pedido antigo"), AIMessage("resposta antiga"), HumanMessage("Sou u-31.")],
        "ctx-1",
    )
    assert pedidos == ["Sou u-31."]
    resposta = final["messages"][-1]
    assert resposta.content[0] == {"type": "text", "text": "Nenhuma reserva para u-31."}
    dados = arquivo_json(resposta)
    assert dados["mensagem"] == "Nenhuma reserva para u-31."
    assert dados["motivo_terminacao"] == "concluido"
    assert final["relatorio"]["tarefa_id"] == dados["tarefa_id"]
    assert "messages" in a2a.A2AState.__annotations__


def test_contexto_mantem_banco_entre_tasks_e_descarta_registros_da_anterior():
    model = ModeloScriptado(
        script=[*script_reserva("workflow"), concluir("Reserva BK-0001 ativa."), concluir("Vazio.")]
    )
    ambientes = {}
    grafo = a2a.build_graph(Context(topologia="workflow"), model, ambientes=ambientes)

    invocar(grafo, [HumanMessage("Sou u-42. Reserve MAD-LIM.")], "ctx-1")
    workspace = ambientes["ctx-1"].workspace
    assert [b["id"] for b in workspace.snapshot()["bookings"]] == ["BK-0001"]
    assert any(e["tipo"] == "tool_call" for e in workspace.eventos)

    final = invocar(grafo, [HumanMessage("Sou u-42. Quais reservas?")], "ctx-1")
    assert ambientes["ctx-1"].workspace is workspace
    assert [b["id"] for b in workspace.snapshot()["bookings"]] == ["BK-0001"]
    # R10 olha os eventos da execução: a busca da task 1 não conta na task 2.
    assert not any(e["tipo"] == "tool_call" for e in workspace.eventos)
    assert workspace.trace == []
    assert final["relatorio"]["mensagem"] == "Reserva BK-0001 ativa."

    invocar(grafo, [HumanMessage("Sou u-42. Quais reservas?")], "ctx-2")
    assert ambientes["ctx-2"].workspace.snapshot()["bookings"] == []
    assert not model.script


def test_execucao_sem_thread_id_usa_ambiente_que_nao_e_guardado():
    model = ModeloScriptado(script=[concluir("ok")])
    ambientes = {}
    invocar(a2a.build_graph(Context(), model, ambientes=ambientes), [HumanMessage("x")])
    assert ambientes == {}


def test_adaptador_recusa_mensagem_sem_texto():
    grafo = a2a.build_graph(Context(), ModeloScriptado(script=[]), ambientes={})
    with pytest.raises(ValueError, match="parte de texto"):
        invocar(grafo, [HumanMessage("   ")], "ctx-1")


def test_langgraph_json_registra_o_adaptador():
    config = json.loads(Path("langgraph.json").read_text())
    entrada_a2a = config["graphs"]["travel_mas_a2a"]
    modulo, nome = entrada_a2a["path"].split(":")
    assert getattr(importlib.import_module(modulo), nome) is a2a.make_graph
    assert entrada_a2a["description"]


class ServidorFalso:
    """Agent Server em memória: busca de assistant, agent card e `message/send`."""

    def __init__(self, relatorios):
        self.relatorios = list(relatorios)
        self.envelopes = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/assistants/search":
            assert json.loads(request.content)["graph_id"] == "travel_mas_a2a"
            return httpx.Response(200, json=[{"assistant_id": UUID}])
        if request.url.path == "/.well-known/agent-card.json":
            assert request.url.params["assistant_id"] == UUID
            return httpx.Response(200, json=CARD)
        assert request.url.path == f"/a2a/{UUID}"
        envelope = json.loads(request.content)
        self.envelopes.append(envelope)
        assert envelope["method"] == "message/send"
        mensagem = envelope["params"]["message"]
        relatorio = self.relatorios.pop(0)
        arquivo = base64.b64encode(json.dumps(relatorio).encode()).decode()
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": envelope["id"],
                "result": {
                    "kind": "task",
                    "id": f"task-{len(self.envelopes)}",
                    "contextId": mensagem.get("contextId", "ctx-novo"),
                    "status": {"state": "completed"},
                    "artifacts": [
                        {
                            "parts": [
                                {"kind": "text", "text": relatorio["mensagem"]},
                                {
                                    "kind": "file",
                                    "file": {
                                        "bytes": arquivo,
                                        "mimeType": "application/json",
                                        "name": "relatorio.json",
                                    },
                                },
                            ]
                        }
                    ],
                },
            },
        )


def test_cliente_resolve_assistant_le_card_e_reenvia_context_id():
    servidor = ServidorFalso(
        [
            {"mensagem": "BK-0001 confirmada.", "booking_ids": ["BK-0001"]},
            {"mensagem": "BK-0001 cancelada.", "booking_ids": []},
        ]
    )
    trocas = []
    cliente = a2a.ClienteA2A(
        "http://teste",
        transport=httpx.MockTransport(servidor),
        observador=lambda direcao, rota, corpo: trocas.append((direcao, rota)),
    )
    assert cliente.card()["name"] == "travel_mas_a2a"
    primeira = cliente.enviar("reserve")
    segunda = cliente.enviar("cancele", primeira.context_id)
    assert (primeira.estado, primeira.context_id, primeira.texto) == (
        "completed",
        "ctx-novo",
        "BK-0001 confirmada.",
    )
    assert primeira.relatorio["booking_ids"] == ["BK-0001"]
    assert "contextId" not in servidor.envelopes[0]["params"]["message"]
    assert servidor.envelopes[1]["params"]["message"]["contextId"] == "ctx-novo"
    assert segunda.task_id == "task-2"
    assert servidor.envelopes[0]["params"]["message"]["parts"] == [
        {"kind": "text", "text": "reserve"}
    ]
    # Uma busca de assistant para as três chamadas; o GET do card só registra a resposta.
    assert trocas.count(("->", "POST /assistants/search")) == 1
    assert ("<-", "GET /.well-known/agent-card.json") in trocas


def test_ler_task_com_erro_json_rpc_e_task_falha():
    with pytest.raises(a2a.ErroA2A, match="-32602"):
        a2a.ler_task({"jsonrpc": "2.0", "error": {"code": -32602, "message": "UUID"}})
    falha = a2a.ler_task(
        {
            "result": {
                "id": "t",
                "contextId": "c",
                "status": {
                    "state": "failed",
                    "message": {"parts": [{"kind": "text", "text": "Error: RuntimeError"}]},
                },
            }
        }
    )
    assert (falha.estado, falha.texto, falha.relatorio) == ("failed", "Error: RuntimeError", None)


def test_ferramenta_do_agente_cliente_vem_do_card_e_mantem_contexto():
    servidor = ServidorFalso([{"mensagem": "um"}, {"mensagem": "dois"}])
    cliente = a2a.ClienteA2A("http://teste", transport=httpx.MockTransport(servidor))
    ferramenta = a2a.ferramenta_a2a(cliente)
    assert ferramenta.name == "a2a_travel_mas_a2a"
    assert CARD["description"] in ferramenta.description
    assert json.loads(ferramenta.invoke({"pedido": "p1"}))["mensagem"] == "um"
    assert json.loads(ferramenta.invoke({"pedido": "p2"}))["relatorio"] == {"mensagem": "dois"}
    assert servidor.envelopes[1]["params"]["message"]["contextId"] == "ctx-novo"


def test_agente_cliente_delega_por_a2a_e_responde():
    servidor = ServidorFalso([{"mensagem": "BK-0001 confirmada.", "booking_ids": ["BK-0001"]}])
    cliente = a2a.ClienteA2A("http://teste", transport=httpx.MockTransport(servidor))
    chamada = {"name": "a2a_travel_mas_a2a", "args": {"pedido": "Sou u-42. Reserve."}, "id": "c1"}
    model = ModeloScriptado(
        script=[AIMessage("", tool_calls=[chamada]), AIMessage("Reservei BK-0001.")]
    )
    agente = a2a.build_agente_cliente(cliente, model=model)
    final = agente.invoke({"messages": [{"role": "user", "content": "Reserve MAD-LIM."}]})
    assert final["messages"][-1].content == "Reservei BK-0001."
    assert servidor.envelopes[0]["params"]["message"]["parts"][0]["text"] == "Sou u-42. Reserve."
    assert "BK-0001" in final["messages"][-2].content
    assert set(model.ferramentas) == {("a2a_travel_mas_a2a",)}


@pytest.fixture
def servidor_na_cli(monkeypatch):
    def instalar(servidor):
        cliente_original = httpx.Client

        def cliente_falso(**kwargs):
            return cliente_original(**{**kwargs, "transport": httpx.MockTransport(servidor)})

        monkeypatch.setattr(cliente_a2a.httpx, "Client", cliente_falso)

    return instalar


def test_cli_a2a_demo_usa_reserva_da_task_1_no_mesmo_contexto(servidor_na_cli, capsys):
    servidor = ServidorFalso(
        [
            {"mensagem": "BK-0007 confirmada.", "booking_ids": ["BK-0007"]},
            {"mensagem": "BK-0007 cancelada.", "booking_ids": []},
        ]
    )
    servidor_na_cli(servidor)
    assert main(["a2a", "demo", "--url", "http://teste"]) == 0
    segunda = servidor.envelopes[1]["params"]["message"]
    assert segunda["contextId"] == "ctx-novo"
    assert "cancele a reserva BK-0007" in segunda["parts"][0]["text"]
    saida = capsys.readouterr().out
    assert "AGENT CARD" in saida and "TASK 2: mesmo contextId" in saida
    assert "BK-0007 cancelada." in saida


def test_cli_a2a_enviar_com_trafego_imprime_envelopes(servidor_na_cli, capsys):
    servidor_na_cli(ServidorFalso([{"mensagem": "ok"}]))
    assert main(["a2a", "enviar", "x", "--contexto", "c9", "--trafego", "--url", "http://t"]) == 0
    saida = capsys.readouterr().out
    assert f"-> POST /a2a/{UUID}" in saida
    assert '"method": "message/send"' in saida
    assert '"contextId": "c9"' in saida


def test_cli_a2a_sem_servidor_falha_com_mensagem(capsys):
    assert main(["a2a", "card", "--url", "http://127.0.0.1:9"]) == 1
    assert "falha HTTP" in capsys.readouterr().err


def test_adaptador_nao_bloqueia_o_laco_de_eventos():
    """O `langgraph dev` recusa I/O bloqueante no laço; o banco nasce fora dele."""
    blockbuster = pytest.importorskip("blockbuster")
    model = ModeloScriptado(script=[concluir("ok"), concluir("ok")])
    grafo = a2a.build_graph(Context(), model, ambientes={})

    async def duas_tasks():
        with blockbuster.blockbuster_ctx():
            for _ in range(2):
                await grafo.ainvoke(
                    {"messages": [HumanMessage("x")]}, {"configurable": {"thread_id": "c"}}
                )

    asyncio.run(duas_tasks())
    assert not model.script


def test_cli_a2a_sai_com_1_quando_o_mas_termina_com_erro(servidor_na_cli, capsys):
    relatorio = {"mensagem": "Falha na execução: 402", "motivo_terminacao": "error"}
    servidor_na_cli(ServidorFalso([relatorio]))
    assert main(["a2a", "enviar", "x", "--url", "http://t"]) == 1
    assert "ESTADO     completed" in capsys.readouterr().out


def test_cliente_busca_o_assistant_do_sistema_e_envia_blocking():
    servidor = ServidorFalso([{"mensagem": "ok"}])
    buscas = []
    original = servidor.__call__

    def registrar(request):
        if request.url.path == "/assistants/search":
            buscas.append(json.loads(request.content))
        return original(request)

    cliente = a2a.ClienteA2A("http://teste", transport=httpx.MockTransport(registrar))
    cliente.enviar("x")
    assert buscas[0]["metadata"] == {"created_by": "system"}
    assert servidor.envelopes[0]["params"]["configuration"]["blocking"] is True


def test_ambientes_guardam_os_contextos_mais_recentes():
    model = ModeloScriptado(script=[concluir("ok") for _ in range(4)])
    ambientes = {}
    grafo = a2a.build_graph(Context(), model, ambientes=ambientes, max_contextos=2)
    for contexto in ("c1", "c2", "c1", "c3"):
        invocar(grafo, [HumanMessage("x")], contexto)
    assert list(ambientes) == ["c1", "c3"]


def test_cli_a2a_agente_delega_e_imprime_resposta(servidor_na_cli, monkeypatch, capsys):
    servidor_na_cli(
        ServidorFalso([{"mensagem": "BK-0001 confirmada.", "booking_ids": ["BK-0001"]}])
    )
    chamada = {"name": "a2a_travel_mas_a2a", "args": {"pedido": "Sou u-42."}, "id": "c1"}
    model = ModeloScriptado(script=[AIMessage("", tool_calls=[chamada]), AIMessage("Feito.")])
    monkeypatch.setattr(
        "travel_mas.interfaces.a2a.agente_cliente.load_chat_model", lambda context: model
    )
    assert main(["a2a", "agente", "Reserve.", "--url", "http://t"]) == 0
    saida = capsys.readouterr().out
    assert "CHAMADA a2a_travel_mas_a2a" in saida and "BK-0001 confirmada." in saida
    assert "RESPOSTA AO USUÁRIO\n  Feito." in saida
