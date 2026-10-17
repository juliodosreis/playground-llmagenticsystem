"""Oráculos de orçamento efetivo e encerramento sem relatório, sem provedor."""

from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

from travel_mas import Context, RunResult, Workspace, build_graph, run_task
from travel_mas.agents.mas import TOPOLOGIAS
from travel_mas.agents.mas.contracts import Decisao, Relatorio, ResultadoPesquisa
from travel_mas.domain import operations
from travel_mas.evaluation.casos import CASOS, Caso, Expectativa
from travel_mas.evaluation.checks import avaliar

from .test_evaluation import fabricado
from .test_mas import ModeloScriptado, chamada, entrada, pedido, script_reserva


@pytest.mark.parametrize(
    "preco,teto,status", [(45, 120, "fail"), (45, 150, "pass"), (999, 150, "pass")]
)
def test_r3_compara_total_guardado_do_hotel(preco, teto, status):
    workspace = Workspace()
    try:
        antes = workspace.snapshot()
        workspace.call(
            operations.create_booking, user_id="u-42", kind="hotel", item_id="HT-2",
            start_date="2026-09-12", price=preco, nights=3,
        )
        workspace.emit("termination", agente="coordenador")
        resultado = RunResult(
            prompt="x", before=antes, after=workspace.snapshot(), trace=workspace.trace,
            final="Reserva concluída.", eventos=deepcopy(workspace.eventos),
            values={"tarefa_id": "t", "relatorio": {"tarefa_id": "t"}, "max_rodadas": 12},
        )
        caso = Caso(
            id="T", nome="orçamento de hotel", solicitud="Hotel por três noites.",
            user_id="u-42", tetos={"hotel": teto}, noites=3,
            regra_origem=["R3"], expectativa=Expectativa(),
        )
        assert resultado.after["bookings"][0]["price"] == 135
        r3 = next(c for c in avaliar(resultado, caso).checks if c.expectativa == "R3")
        assert r3.status == status
    finally:
        workspace.db.close()


@pytest.mark.parametrize("topologia", TOPOLOGIAS)
@pytest.mark.parametrize("mensagem", [None, "", "   "])
def test_fim_sem_relatorio_valido_registra_erro_e_reprova_r11(topologia, mensagem):
    def concluir(messages):
        return Decisao(
            proximo="fim",
            relatorio=(
                Relatorio(tarefa_id=entrada(messages)["tarefa_id"], mensagem=mensagem)
                if mensagem is not None else None
            ),
        )

    model = ModeloScriptado(script=script_reserva(topologia)[:-1] + [concluir])
    workspace = Workspace()
    try:
        resultado = run_task(
            build_graph(workspace, Context(topologia=topologia), model),
            workspace, CASOS["C01"].solicitud,
        )
        assert not model.script
        assert len(resultado.bookings()) == 1
        assert resultado.error == "relatorio_ausente"
        assert resultado.values["motivo_terminacao"] == "error"
        assert any(e["tipo"] == "error" for e in resultado.eventos)
        r11 = next(c for c in avaliar(resultado, CASOS["C01"]).checks if c.expectativa == "R11")
        assert r11.status == "fail"
    finally:
        workspace.db.close()


def test_r11_reprova_relatorio_ausente_em_traca_historica_sem_error():
    resultado = fabricado()
    resultado.values["relatorio"]["erros"] = ["relatorio_ausente"]
    resultado.values["motivo_terminacao"] = "concluido"
    assert resultado.error is None
    r11 = next(c for c in avaliar(resultado, CASOS["C01"]).checks if c.expectativa == "R11")
    assert r11.status == "fail"


@pytest.mark.parametrize("topologia", TOPOLOGIAS)
@pytest.mark.parametrize("motivo", ["max_rodadas", "limite_repropostas"])
def test_encerramento_forcado_sem_mensagem_preserva_motivo_original(topologia, motivo):
    def pedido_sem_voos(messages):
        decisao = pedido(messages)
        decisao.pedido.itens[0].data = "2026-09-14"
        return decisao

    script = [pedido]
    context = Context(topologia=topologia, max_rodadas=2)
    if motivo == "limite_repropostas":
        context = Context(topologia=topologia)
        script = [
            pedido_sem_voos,
            chamada("search_flights", {"origin": "MAD", "destination": "LIM",
                                      "date": "2026-09-14"}, "busca"),
            AIMessage("Nenhum voo encontrado."),
            ResultadoPesquisa(propostas=[], motivo="Nenhum voo em 2026-09-14."),
            Decisao(proximo="pesquisador"),
        ]
    script.append(lambda m: Relatorio(tarefa_id=entrada(m)["tarefa_id"], mensagem=" "))
    model = ModeloScriptado(script=script)
    workspace = Workspace()
    try:
        resultado = run_task(
            build_graph(workspace, context, model),
            workspace, CASOS["C01"].solicitud,
        )
        assert not model.script
        assert resultado.error == "relatorio_ausente"
        assert resultado.values["motivo_terminacao"] == "error"
        erro = next(e for e in resultado.eventos if e["tipo"] == "error")
        assert erro["motivo_original"] == motivo
    finally:
        workspace.db.close()
