"""Revisão aprovada depois da rejeição, nas duas topologias, sem provedor."""

import pytest
from langchain_core.messages import AIMessage

from travel_mas import Context, Workspace, build_graph, run_task
from travel_mas.agents.mas import TOPOLOGIAS
from travel_mas.agents.mas.contracts import Decisao, Ordem, Proposta, ResultadoPesquisa
from travel_mas.evaluation.casos import CASOS
from travel_mas.evaluation.checks import avaliar

from .test_mas import (
    ModeloScriptado,
    chamada,
    entrada,
    finalizar,
    pedido,
    relatorio,
    veredito,
)


@pytest.mark.parametrize("topologia", TOPOLOGIAS)
def test_c03_revisao_aprovada_reserva_apenas_alternativa(topologia):
    def solicitar(messages):
        decisao = pedido(messages)
        decisao.pedido.itens[0].data = "2026-09-15"
        return decisao

    def propor(pid, item, preco, evidencia):
        def responder(messages):
            return ResultadoPesquisa(
                propostas=[
                    Proposta(
                        tarefa_id=entrada(messages)["bandeja"][0]["conteudo"]["tarefa_id"],
                        proposta_id=pid,
                        kind="flight",
                        item_id=item,
                        price_total=preco,
                        date="2026-09-15",
                        evidencia=evidencia,
                    )
                ]
            )

        return responder

    def autorizar(messages):
        return Decisao(
            proximo="reservador",
            ordens=[
                Ordem(tarefa_id=entrada(messages)["tarefa_id"], proposta_id="p2", user_id="u-42")
            ],
        )

    busca = {"origin": "MAD", "destination": "LIM", "date": "2026-09-15"}
    script = [
        solicitar,
        chamada("search_flights", busca, "b1"),
        AIMessage("Voo mais barato encontrado."),
        propor("p1", "FL-105", 650, "b1"),
        *([Decisao(proximo="verificador")] if topologia == "supervisor" else []),
        chamada("check_item", {"kind": "flight", "item_id": "FL-105"}, "c1"),
        AIMessage("Sem assentos."),
        lambda m: veredito(m, False),
        *([Decisao(proximo="pesquisador")] if topologia == "supervisor" else []),
        chamada("search_flights", busca, "b2"),
        AIMessage("Próxima opção: FL-106."),
        propor("p2", "FL-106", 820, "b2"),
        *([Decisao(proximo="verificador")] if topologia == "supervisor" else []),
        chamada("check_item", {"kind": "flight", "item_id": "FL-106"}, "c2"),
        AIMessage("Aprovado com assentos disponíveis."),
        veredito,
        autorizar,
        chamada("list_bookings", {"user_id": "u-42"}, "lista"),
        chamada(
            "create_booking",
            {"user_id": "u-42", "kind": "flight", "item_id": "FL-106",
             "start_date": "2026-09-15", "price": 820},
            "criar",
        ),
        chamada("get_booking", {"booking_id": "BK-0001"}, "confirmar"),
        AIMessage("BK-0001 confirmada."),
        relatorio,
        finalizar,
    ]
    workspace = Workspace()
    model = ModeloScriptado(script=script)
    result = run_task(
        build_graph(workspace, Context(topologia=topologia), model),
        workspace,
        CASOS["C03"].solicitud,
    )
    assert result.error is None, result.to_dict()
    assert not model.script
    assert result.values["pesquisas"] == 2
    assert [r["item_id"] for r in result.bookings()] == ["FL-106"]
    assert avaliar(result, CASOS["C03"]).status == "pass"
