"""Contratos, isolamento, permissões e execução dos grafos sem provedor externo."""

import asyncio
import json
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field, ValidationError

from travel_mas import Context, Workspace, build_graph, run_task
from travel_mas.agents.mas import AGENTES, TOPOLOGIAS
from travel_mas.agents.mas.contracts import (
    Decisao,
    Ordem,
    Pedido,
    Proposta,
    Relatorio,
    ResultadoPesquisa,
    ResultadoVerificacao,
    Veredito,
)
from travel_mas.agents.mas.graph import MASState, entregar
from travel_mas.cli import build_parser, main
from travel_mas.domain import operations
from travel_mas.evaluation import combine_specs, compare_models
from travel_mas.runtime.structured import preencher
from travel_mas.tools import build_toolbox


class ModeloScriptado(BaseChatModel):
    """Respostas em fila; percorre ReAct real e a conversão estruturada real."""

    script: list[Any]
    chamadas: list = Field(default_factory=list)
    ferramentas: list = Field(default_factory=list)
    esquemas: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "mas-scriptado"

    def responder(self, messages, schema=None):
        self.chamadas.append(messages)
        assert self.script, "script esgotado"
        resposta = self.script.pop(0)
        if callable(resposta):
            resposta = resposta(messages)
        if schema is not None:
            return schema.model_validate(resposta)
        assert isinstance(resposta, AIMessage)
        return resposta.model_copy(update={"id": None})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.responder(messages))])

    def bind_tools(self, tools, **kwargs):
        self.ferramentas.append(tuple(tool.name for tool in tools))
        return RunnableLambda(self.responder)

    def with_structured_output(self, schema, *, method, **kwargs):
        self.esquemas.append((schema, method))
        return RunnableLambda(lambda messages: self.responder(messages, schema))


def entrada(messages):
    """A entrada da ativação atual: a última mensagem do pai no histórico privado."""
    for m in reversed(messages):
        if isinstance(m, HumanMessage) and m.content.startswith("{"):
            return json.loads(m.content)
    raise AssertionError("sem entrada do pai")


def pedido(messages):
    return Decisao(
        proximo="pesquisador",
        pedido=Pedido(
            tarefa_id=entrada(messages)["tarefa_id"],
            user_id="u-42",
            acao="reservar",
            itens=[
                {
                    "kind": "flight",
                    "data": "2026-09-12",
                    "origem": "MAD",
                    "destino": "LIM",
                    "teto": 1000,
                }
            ],
        ),
    )


def proposta(messages):
    tarefa_id = entrada(messages)["bandeja"][0]["conteudo"]["tarefa_id"]
    return ResultadoPesquisa(
        propostas=[
            Proposta(
                tarefa_id=tarefa_id,
                proposta_id="p1",
                kind="flight",
                item_id="FL-101",
                price_total=980,
                date="2026-09-12",
                evidencia="busca-privada",
            )
        ]
    )


def veredito(messages, aprovado=True):
    p = next(e["conteudo"] for e in entrada(messages)["bandeja"] if e["tipo"] == "Proposta")
    return ResultadoVerificacao(
        vereditos=[
            Veredito(
                tarefa_id=p["tarefa_id"],
                proposta_id=p["proposta_id"],
                aprovado=aprovado,
                motivo="consultado" if aprovado else "rejeitado",
            )
        ]
    )


def ordem(messages):
    dados = entrada(messages)
    return Decisao(
        proximo="reservador",
        ordens=[
            {
                "tarefa_id": dados["tarefa_id"],
                "proposta_id": "p1",
                "user_id": "u-42",
            }
        ],
    )


def relatorio(messages):
    tarefa = entrada(messages).get("tarefa_id")
    if tarefa is None:
        tarefa = entrada(messages)["bandeja"][0]["conteudo"]["tarefa_id"]
    return Relatorio(tarefa_id=tarefa, booking_ids=["BK-0001"], mensagem="BK-0001 confirmada.")


def finalizar(messages):
    return Decisao(proximo="fim", relatorio=relatorio(messages))


def chamada(nome, args, identificador):
    return AIMessage("", tool_calls=[{"name": nome, "args": args, "id": identificador}])


def script_reserva(topologia):
    script = [
        pedido,
        chamada(
            "search_flights",
            {"origin": "MAD", "destination": "LIM", "date": "2026-09-12"},
            "busca-privada",
        ),
        AIMessage("pesquisa feita"),
        proposta,
    ]
    if topologia == "supervisor":
        script += [Decisao(proximo="verificador")]
    script += [
        chamada("check_item", {"kind": "flight", "item_id": "FL-101"}, "check"),
        AIMessage("verificado"),
        veredito,
        ordem,
        chamada("list_bookings", {"user_id": "u-42"}, "lista"),
        chamada(
            "create_booking",
            {
                "user_id": "u-42",
                "kind": "flight",
                "item_id": "FL-101",
                "start_date": "2026-09-12",
                "price": 980,
            },
            "criar",
        ),
        chamada("get_booking", {"booking_id": "BK-0001"}, "confirmar"),
        AIMessage("reservado"),
        relatorio,
        finalizar,
    ]
    return script


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.setenv("TRAVEL_TOPOLOGIA", "workflow")

    def bloquear(_):
        raise AssertionError("teste tentou carregar um provedor")

    monkeypatch.setattr("travel_mas.agents.mas.graph.load_chat_model", bloquear)
    monkeypatch.setattr("travel_mas.cli.load_dotenv", lambda *args: None)


@pytest.mark.parametrize("topologia", TOPOLOGIAS)
def test_reserva_com_quatro_historicos_privados(topologia):
    workspace = Workspace()
    model = ModeloScriptado(script=script_reserva(topologia))
    agent = build_graph(workspace, Context(topologia=topologia), model)
    result = run_task(agent, workspace, "PEDIDO PRIVADO: reserve para u-42.")
    assert result.error is None, result.to_dict()
    assert not model.script
    assert result.bookings()[0]["item_id"] == "FL-101"
    assert result.bookings()[0]["user_id"] == "u-42"
    assert result.after["flights"][0]["seats"] == result.before["flights"][0]["seats"] - 1
    assert result.final == "BK-0001 confirmada."
    assert result.eventos[-1]["tipo"] == "termination"
    assert result.values["rodada"] <= 8
    assert "messages" not in MASState.__annotations__
    assert "messages" not in result.values
    for messages in model.chamadas:
        role = messages[0].content
        if "Você é o Verificador" in role:
            assert "busca-privada" in str(messages)  # referência tipada permitida
            assert not any(m.type == "tool" and m.name == "search_flights" for m in messages)
            assert "PEDIDO PRIVADO" not in str(messages)
        if "Você é o Pesquisador" in role:
            resultados = [m for m in messages if m.type == "tool"]
            if resultados:
                assert json.loads(resultados[0].content)["evidencia"] == "busca-privada"
        if "Você é o Reservador" in role:
            assert "PEDIDO PRIVADO" not in str(messages)
            assert not any(m.type == "tool" and m.name == "check_item" for m in messages)
    assert all(method == "function_calling" for _, method in model.esquemas)
    assert {tuple(x) for x in model.ferramentas} == {
        ("search_flights", "search_hotels"),
        ("check_item",),
        ("create_booking", "get_booking", "list_bookings", "cancel_booking"),
    }
    criar = next(
        e
        for e in result.eventos
        if e["tipo"] == "tool_call" and e["ferramenta"] == "create_booking"
    )
    assert criar["agente"] == "reservador"
    assert criar["chamada_id"] == "criar"
    assert [e for e in result.eventos if e["tipo"] == "handoff"] == result.bitacora
    json.dumps(result.to_dict())


@pytest.mark.parametrize("topologia", TOPOLOGIAS)
def test_rejeicao_retorna_ao_pesquisador_e_nao_escreve(topologia):
    script = [pedido, AIMessage("proposta"), proposta]
    if topologia == "supervisor":
        script += [Decisao(proximo="verificador")]
    script += [AIMessage("rejeitar"), lambda m: veredito(m, False)]
    if topologia == "supervisor":
        script += [Decisao(proximo="pesquisador")]
    script += [
        AIMessage("sem alternativa"),
        ResultadoPesquisa(propostas=[], motivo="sem opção"),
        lambda m: Decisao(
            proximo="fim",
            relatorio=Relatorio(tarefa_id=entrada(m)["tarefa_id"], mensagem="Sem opção."),
        ),
    ]
    workspace = Workspace()
    model = ModeloScriptado(script=script)
    result = run_task(build_graph(workspace, Context(topologia=topologia), model), workspace, "x")
    assert result.error is None, result.to_dict()
    assert not model.script
    assert result.bookings() == []
    assert result.values["pesquisas"] == 2
    assert any(e["de"] == "verificador" and e["para"] == "pesquisador" for e in result.bitacora)


@pytest.mark.parametrize("texto", ["Que clima faz em Lima?", "Reserve um voo sem user_id."])
def test_coordenador_pode_recusar_ou_pedir_esclarecimento_sem_ferramentas(texto):
    model = ModeloScriptado(
        script=[
            lambda m: Decisao(
                proximo="fim",
                relatorio=Relatorio(
                    tarefa_id=entrada(m)["tarefa_id"],
                    mensagem="Informe o usuário ou um pedido de viagem.",
                ),
            ),
        ]
    )
    workspace = Workspace()
    result = run_task(build_graph(workspace, Context(), model), workspace, texto)
    assert result.error is None
    assert not result.trace and not result.bitacora
    assert result.final


def test_limite_de_rodadas_reserva_relatorio_final():
    model = ModeloScriptado(script=[pedido, relatorio])
    workspace = Workspace()
    result = run_task(build_graph(workspace, Context(max_rodadas=2), model), workspace, "x")
    assert result.error is None
    assert result.values["rodada"] == 2
    assert result.eventos[-1]["motivo"] == "max_rodadas"
    assert not result.trace and result.values["relatorio"]


def test_falha_de_modelo_termina_com_relatorio_e_erro():
    model = ModeloScriptado(script=[])
    workspace = Workspace()
    result = run_task(build_graph(workspace, Context(), model), workspace, "x")
    assert result.error
    assert result.final and result.values["relatorio"]["erros"]
    assert result.eventos[-1]["motivo"] == "error"


def test_entrega_copia_apenas_contratos_e_registra():
    workspace = Workspace()
    state = {"bandejas": {nome: [] for nome in AGENTES}, "bitacora": []}
    mensagem = Pedido(tarefa_id="t", user_id="u", itens=[], acao="listar")
    entregar("coordenador", "reservador", mensagem, state=state, workspace=workspace)
    mensagem.user_id = "outro"
    assert state["bandejas"]["reservador"][0]["conteudo"]["user_id"] == "u"
    assert state["bitacora"][0]["mensagem_tipo"] == "Pedido"
    with pytest.raises(TypeError):
        entregar(
            "coordenador", "reservador", Decisao(proximo="fim"), state=state, workspace=workspace
        )


def test_preenchimento_reintenta_none_e_schema_invalido():
    respostas = iter([None, {}, Relatorio(tarefa_id="t")])
    chamadas = []

    def responder(mensagens):
        chamadas.append(list(mensagens))
        return next(respostas)

    runnable = RunnableLambda(responder)
    result = asyncio.run(preencher(runnable, [HumanMessage("x")], Relatorio))
    assert result.tarefa_id == "t"
    assert len(chamadas) == 3
    assert "tarefa_id" in chamadas[0][-1].content
    assert "recusada" in chamadas[1][-1].content
    with pytest.raises(RuntimeError, match="3 tentativas"):
        asyncio.run(preencher(RunnableLambda(lambda _: None), [], Relatorio))


def test_ferramenta_de_outro_papel_nao_pode_escrever():
    workspace = Workspace()
    model = ModeloScriptado(
        script=[
            chamada(
                "create_booking",
                {
                    "user_id": "u-42",
                    "kind": "flight",
                    "item_id": "FL-101",
                    "start_date": "2026-09-12",
                    "price": 980,
                },
                "proibida",
            ),
            AIMessage("não posso reservar"),
            ResultadoPesquisa(propostas=[], motivo="sem permissão"),
        ]
    )
    graph = AGENTES["pesquisador"](model, build_toolbox(workspace), Context())
    result = asyncio.run(graph.ainvoke({"messages": [HumanMessage("{}")], "passos": 0}))
    assert result["saida"]["propostas"] == []
    assert workspace.snapshot()["bookings"] == [] and workspace.trace == []
    assert any(m.type == "tool" and m.status == "error" for m in result["messages"])


def test_grafo_reutilizado_nao_herda_bandejas_eventos_ou_reservas():
    workspace = Workspace()
    model = ModeloScriptado(script=script_reserva("workflow") + script_reserva("workflow"))
    agent = build_graph(workspace, Context(), model)
    primeiro = run_task(agent, workspace, "pedido um")
    segundo = run_task(agent, workspace, "pedido dois")
    assert primeiro.error is None and segundo.error is None
    assert len(primeiro.bookings()) == len(segundo.bookings()) == 1
    assert segundo.before["bookings"] == []
    assert primeiro.values["tarefa_id"] != segundo.values["tarefa_id"]
    assert len(primeiro.eventos) == len(segundo.eventos)
    assert segundo.eventos[0]["seq"] == 1


def test_max_steps_interrompe_react_com_chamadas_pendentes():
    workspace = Workspace()
    busca = chamada(
        "search_flights", {"origin": "MAD", "destination": "LIM", "date": "2026-09-12"}, "busca"
    )
    model = ModeloScriptado(script=[pedido, busca, busca, relatorio])
    result = run_task(build_graph(workspace, Context(max_steps=2), model), workspace, "x")
    assert result.error
    assert result.tool_names() == ["search_flights"]
    assert result.bookings() == [] and result.values["relatorio"]
    assert any(e["tipo"] == "error" and "max_steps" in e["erro"] for e in result.eventos)


def test_check_item_e_total_de_hotel():
    workspace = Workspace()
    antes = workspace.snapshot()
    item = json.loads(operations.check_item(workspace.db, "flight", "FL-101"))
    assert item["seats"] == 4 and item["price"] == 980
    assert workspace.snapshot() == antes
    assert json.loads(operations.check_item(workspace.db, "flight", "ausente"))["error"]
    operations.create_booking(workspace.db, "u", "hotel", "HT-2", "2026-09-12", 45, nights=3)
    assert workspace.snapshot()["bookings"][0]["price"] == 135
    assert workspace.snapshot()["bookings"][0]["nights"] == 3


def test_permissoes_nao_criam_candados_para_regras_normativas():
    workspace = Workspace()
    # O avaliador poderá observar duplicatas; R1/R6/R7 não são bloqueios no domínio.
    for _ in range(2):
        operations.create_booking(workspace.db, "u", "flight", "FL-101", "2026-09-12", 980)
    assert len(workspace.snapshot()["bookings"]) == 2


def test_catalogo_cli_topologias_e_comparacao(capsys):
    assert main(["catalogo"]) == 0
    assert "FL-101" in capsys.readouterr().out
    args = build_parser().parse_args(
        [
            "comparar",
            "--topologia",
            "workflow",
            "--topologia",
            "supervisor",
            "1",
        ]
    )
    assert args.topologia_comparar == ["workflow", "supervisor"]
    specs = combine_specs(["ollama", "google"], list(TOPOLOGIAS))
    assert len(specs) == 4 and len({s.label for s in specs}) == 4
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--tools", "mcp", "catalogo"])
    with pytest.raises(ValidationError):
        Proposta(
            tarefa_id="t",
            proposta_id="p",
            kind="flight",
            item_id="f",
            price_total=1,
            date="2026-09-12",
        )


def test_comparar_executa_as_duas_topologias_pela_cli(monkeypatch, capsys):
    def montar(workspace, context):
        return build_graph(
            workspace, context, ModeloScriptado(script=script_reserva(context.topologia))
        )

    def comparar(specs, keys):
        resultado = compare_models(specs, keys, build=montar)
        assert resultado.agreed() == 1
        assert all(run.error is None for run in resultado.scenarios[0].runs)
        return resultado

    monkeypatch.setattr("travel_mas.cli.compare_models", comparar)
    assert main(["comparar", "--topologia", "workflow", "--topologia", "supervisor", "1"]) == 0
    saida = capsys.readouterr().out
    assert "workflow" in saida and "supervisor" in saida and "igual" in saida


def tipos(messages):
    return [e["tipo"] for e in entrada(messages)["bandeja"]]


def resultados_de(messages, ferramenta):
    return [m for m in messages if m.type == "tool" and m.name == ferramenta]


@pytest.mark.parametrize("topologia", TOPOLOGIAS)
def test_timeout_persistente_nao_reabre_pesquisa_sem_rejeicao(topologia):
    # C12P: nova pesquisa após um Relatorio de erro não pode reiniciar os reintentos esgotados.
    from travel_mas.evaluation.casos import CASOS
    from travel_mas.evaluation.checks import avaliar

    busca = {"origin": "MAD", "destination": "LIM", "date": "2026-09-12"}

    def encerrar(messages):
        assert entrada(messages)["motivo_terminacao"] == "limite_repropostas"
        return Relatorio(
            tarefa_id=entrada(messages)["tarefa_id"],
            erros=["timeout"],
            mensagem="Falha: timeout persistente na busca de voos; nenhuma reserva.",
        )

    model = ModeloScriptado(
        script=[
            pedido,
            chamada("search_flights", busca, "t1"),
            chamada("search_flights", busca, "t2"),
            AIMessage("a busca falhou duas vezes"),
            ResultadoPesquisa(propostas=[], motivo="timeout persistente"),
            pedido,
            encerrar,
        ]
    )
    workspace = Workspace()
    caso = CASOS["C12P"]
    result = run_task(
        build_graph(workspace, Context(topologia=topologia), model),
        workspace,
        caso.solicitud,
        tool_faults=caso.tool_faults,
    )
    assert not model.script
    assert result.tool_names() == ["search_flights", "search_flights"]
    assert result.values["pesquisas"] == 1
    assert result.eventos[-1]["motivo"] == "limite_repropostas"
    assert (Relatorio, "function_calling") in model.esquemas
    assert avaliar(result, caso).status == "pass", avaliar(result, caso).to_dict()


@pytest.mark.parametrize("topologia", TOPOLOGIAS)
def test_revisao_recebe_historico_e_encerramento_informa_menor_preco(topologia):
    # C04: após a segunda rejeição, o fechamento deve conservar o menor preço observado.
    from travel_mas.evaluation.casos import CASOS
    from travel_mas.evaluation.checks import avaliar

    busca = {"origin": "MAD", "destination": "LIM", "date": "2026-09-12"}

    def pedido_700(messages):
        decisao = pedido(messages)
        decisao.pedido.itens[0].teto = 700
        return decisao

    def proposta_de(pid, item, preco, evidencia):
        return lambda m: ResultadoPesquisa(
            propostas=[
                Proposta(
                    tarefa_id=entrada(m)["bandeja"][0]["conteudo"]["tarefa_id"],
                    proposta_id=pid,
                    kind="flight",
                    item_id=item,
                    price_total=preco,
                    date="2026-09-12",
                    evidencia=evidencia,
                )
            ]
        )

    def revisar(messages):
        assert tipos(messages) == ["Veredito", "Proposta"]
        buscas = resultados_de(messages, "search_flights")
        assert [json.loads(m.content)["evidencia"] for m in buscas] == ["b1"]
        return chamada("search_flights", busca, "b2")

    def verificar_nova(messages):
        assert tipos(messages) == ["Proposta"]
        return chamada("check_item", {"kind": "flight", "item_id": "FL-102"}, "c2")

    def encerrar(messages):
        assert entrada(messages)["motivo_terminacao"] == "limite_repropostas"
        return Relatorio(
            tarefa_id=entrada(messages)["tarefa_id"],
            mensagem="Nenhum voo até 700 EUR. Menor preço observado: 980 EUR.",
        )

    model = ModeloScriptado(
        script=[
            pedido_700,
            chamada("search_flights", busca, "b1"),
            AIMessage("FL-101 é o mais barato"),
            proposta_de("p1", "FL-101", 980, "b1"),
            *([Decisao(proximo="verificador")] if topologia == "supervisor" else []),
            chamada("check_item", {"kind": "flight", "item_id": "FL-101"}, "c1"),
            AIMessage("acima do teto"),
            lambda m: veredito(m, False),
            *([Decisao(proximo="pesquisador")] if topologia == "supervisor" else []),
            revisar,
            AIMessage("próxima opção FL-102"),
            proposta_de("p2", "FL-102", 1240, "b2"),
            *([Decisao(proximo="verificador")] if topologia == "supervisor" else []),
            verificar_nova,
            AIMessage("acima do teto"),
            lambda m: veredito(m, False),
            pedido_700,
            encerrar,
        ]
    )
    workspace = Workspace()
    result = run_task(
        build_graph(workspace, Context(topologia=topologia), model),
        workspace,
        CASOS["C04"].solicitud,
    )
    assert not model.script, result.to_dict()
    assert result.values["pesquisas"] == 2
    assert "980" in result.final
    assert avaliar(result, CASOS["C04"]).status == "pass", avaliar(result, CASOS["C04"]).to_dict()


@pytest.mark.parametrize("topologia", TOPOLOGIAS)
def test_reservador_executa_so_ordens_novas_e_lembra_reserva_criada(topologia):
    # C13: uma Ordem nova não deve reenviar a Ordem de reserva já executada.
    from travel_mas.evaluation.casos import CASOS
    from travel_mas.evaluation.checks import avaliar

    def pedido_c13(messages):
        return Decisao(
            proximo="pesquisador",
            pedido=Pedido(
                tarefa_id=entrada(messages)["tarefa_id"],
                user_id="u-55",
                acao="reservar",
                listar_depois=True,
                cancelar_depois=True,
                itens=[
                    {
                        "kind": "flight",
                        "data": "2026-09-20",
                        "origem": "LIM",
                        "destino": "MAD",
                        "teto": 900,
                    }
                ],
            ),
        )

    def proposta_c13(messages):
        return ResultadoPesquisa(
            propostas=[
                Proposta(
                    tarefa_id=entrada(messages)["bandeja"][0]["conteudo"]["tarefa_id"],
                    proposta_id="p1",
                    kind="flight",
                    item_id="FL-201",
                    price_total=890,
                    date="2026-09-20",
                    evidencia="busca",
                )
            ]
        )

    def ordem_c13(messages):
        return Decisao(
            proximo="reservador",
            ordens=[
                Ordem(
                    tarefa_id=entrada(messages)["tarefa_id"],
                    proposta_id="p1",
                    user_id="u-55",
                    listar_depois=True,
                    cancelar_depois=True,
                )
            ],
        )

    def ordens_repetidas(messages):
        tarefa = entrada(messages)["tarefa_id"]
        return Decisao(
            proximo="reservador",
            ordens=[
                Ordem(tarefa_id=tarefa, user_id="u-55", acao="listar"),
                Ordem(tarefa_id=tarefa, user_id="u-55", acao="cancelar", booking_id="BK-0001"),
            ],
        )

    def segunda_ativacao(messages):
        assert tipos(messages) == ["Ordem", "Ordem"]
        assert len(resultados_de(messages, "create_booking")) == 1
        return chamada("list_bookings", {"user_id": "u-55"}, "lista3")

    criar = {
        "user_id": "u-55",
        "kind": "flight",
        "item_id": "FL-201",
        "start_date": "2026-09-20",
        "price": 890,
    }
    model = ModeloScriptado(
        script=[
            pedido_c13,
            chamada(
                "search_flights",
                {"origin": "LIM", "destination": "MAD", "date": "2026-09-20"},
                "busca",
            ),
            AIMessage("FL-201"),
            proposta_c13,
            *([Decisao(proximo="verificador")] if topologia == "supervisor" else []),
            chamada("check_item", {"kind": "flight", "item_id": "FL-201"}, "check"),
            AIMessage("aprovado"),
            veredito,
            ordem_c13,
            chamada("list_bookings", {"user_id": "u-55"}, "lista"),
            chamada("create_booking", criar, "criar"),
            chamada("get_booking", {"booking_id": "BK-0001"}, "confirmar"),
            chamada("list_bookings", {"user_id": "u-55"}, "lista2"),
            chamada("cancel_booking", {"booking_id": "BK-0001"}, "cancelar"),
            AIMessage("criada, listada e cancelada"),
            relatorio,
            ordens_repetidas,
            segunda_ativacao,
            AIMessage("BK-0001 já está cancelled"),
            relatorio,
            finalizar,
        ]
    )
    workspace = Workspace()
    caso = CASOS["C13"]
    result = run_task(
        build_graph(workspace, Context(topologia=topologia), model), workspace, caso.solicitud
    )
    assert not model.script, result.to_dict()
    assert result.tool_names().count("create_booking") == 1
    assert [e["mensagem_tipo"] for e in result.bitacora if e["para"] == "reservador"] == [
        "Ordem",
        "Proposta",
        "Veredito",
        "Ordem",
        "Ordem",
    ]
    assert avaliar(result, caso).status == "pass", avaliar(result, caso).to_dict()


@pytest.mark.parametrize("topologia", TOPOLOGIAS)
def test_pedido_corrigido_sem_busca_executada_abre_nova_pesquisa(topologia):
    # Um Pedido sem cidade e sem busca executada admite pesquisa com o Pedido corrigido.
    def pedido_hotel(cidade):
        def decidir(messages):
            return Decisao(
                proximo="pesquisador",
                pedido=Pedido(
                    tarefa_id=entrada(messages)["tarefa_id"],
                    user_id="u-42",
                    acao="reservar",
                    itens=[{"kind": "hotel", "data": "2026-09-12", "cidade": cidade, "noites": 3}],
                ),
            )

        return decidir

    model = ModeloScriptado(
        script=[
            pedido_hotel(None),
            AIMessage("falta a cidade"),
            ResultadoPesquisa(propostas=[], motivo="falta cidade"),
            pedido_hotel("LIM"),
            chamada("search_hotels", {"city": "LIM"}, "h1"),
            AIMessage("sem opção no teto"),
            ResultadoPesquisa(propostas=[], motivo="sem opção"),
            pedido_hotel("LIM"),
            lambda m: Relatorio(tarefa_id=entrada(m)["tarefa_id"], mensagem="Sem opção."),
        ]
    )
    workspace = Workspace()
    result = run_task(build_graph(workspace, Context(topologia=topologia), model), workspace, "x")
    assert not model.script, result.to_dict()
    assert result.tool_names() == ["search_hotels"]
    assert result.values["pesquisas"] == 2
    assert result.eventos[-1]["motivo"] == "limite_repropostas"


@pytest.mark.parametrize("reserva_parcial", [False, True])
@pytest.mark.parametrize("topologia", TOPOLOGIAS)
def test_c06_avalia_reserva_atomica_do_pedido_combinado(reserva_parcial, topologia):
    from travel_mas.evaluation.casos import CASOS
    from travel_mas.evaluation.checks import avaliar

    def pedido_combinado(messages):
        return Decisao(
            proximo="pesquisador",
            pedido=Pedido(
                tarefa_id=entrada(messages)["tarefa_id"],
                user_id="u-42",
                acao="reservar",
                itens=[
                    {"kind": "flight", "data": "2026-09-12", "origem": "MAD", "destino": "LIM",
                     "teto": 1000},
                    {"kind": "hotel", "data": "2026-09-12", "cidade": "XYZ", "teto": 100},
                ],
            ),
        )

    def concluir(messages):
        tarefa = entrada(messages)["tarefa_id"]
        if reserva_parcial:
            return Decisao(
                proximo="reservador",
                ordens=[Ordem(tarefa_id=tarefa, proposta_id="p1", user_id="u-42")],
            )
        return Decisao(
            proximo="fim",
            relatorio=Relatorio(
                tarefa_id=tarefa,
                mensagem="Nenhuma reserva: não há hotel em XYZ. O voo FL-101 custa 980 EUR.",
            ),
        )

    script = [
        pedido_combinado,
        chamada("search_flights", {"origin": "MAD", "destination": "LIM", "date": "2026-09-12"},
                "busca-privada"),
        chamada("search_hotels", {"city": "XYZ"}, "hoteis"),
        AIMessage("voo encontrado; nenhum hotel em XYZ"),
        proposta,
        *([Decisao(proximo="verificador")] if topologia == "supervisor" else []),
        chamada("check_item", {"kind": "flight", "item_id": "FL-101"}, "check"),
        AIMessage("voo aprovado"),
        veredito,
        concluir,
    ]
    if reserva_parcial:
        script += script_reserva(topologia)[-6:]
    workspace = Workspace()
    model = ModeloScriptado(script=script)
    result = run_task(
        build_graph(workspace, Context(topologia=topologia), model),
        workspace,
        CASOS["C06"].solicitud,
    )
    assert not model.script, result.to_dict()
    avaliacao = avaliar(result, CASOS["C06"])
    if reserva_parcial:
        falhas = {c.regra_origem.rsplit(".", 1)[-1] for c in avaliacao.checks if c.status == "fail"}
        assert avaliacao.status == "fail" and "R4" in falhas
    else:
        assert avaliacao.status == "pass", avaliacao.to_dict()
