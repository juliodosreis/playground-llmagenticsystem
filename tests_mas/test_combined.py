"""Pedidos combinados com disponibilidade parcial e relatório final, sem provedor."""

import pytest
from langchain_core.messages import AIMessage

from travel_mas import Context, Workspace, build_graph, run_task
from travel_mas.agents.mas import TOPOLOGIAS
from travel_mas.agents.mas.contracts import Decisao, ItemPedido, Relatorio
from travel_mas.evaluation.casos import CASOS
from travel_mas.evaluation.checks import avaliar

from .test_mas import ModeloScriptado, chamada, entrada, pedido, proposta, veredito

MOTIVO = "Nenhum hotel em XYZ em 2026-09-12; a busca retornou lista vazia."


def pedido_combinado(messages):
    decisao = pedido(messages)
    decisao.pedido.itens.append(
        ItemPedido(kind="hotel", data="2026-09-12", cidade="XYZ", noites=1, teto=100)
    )
    return decisao


def pesquisa_parcial(messages):
    resultado = proposta(messages)
    resultado.motivo = MOTIVO
    return resultado


@pytest.mark.parametrize("topologia", TOPOLOGIAS)
@pytest.mark.parametrize("forcar_encerramento", [False, True])
def test_pesquisa_parcial_preserva_motivo_e_preco_no_coordenador(topologia, forcar_encerramento):
    def conferir(messages):
        # Só as transferências públicas chegam ao Coordenador, incluindo o motivo parcial.
        nova = entrada(messages)["bandeja"]
        informes = [e["conteudo"] for e in nova if e["tipo"] == "Relatorio"]
        assert len(informes) == 1
        assert informes[0]["mensagem"] == MOTIVO
        assert informes[0]["erros"] == [informes[0]["mensagem"]]
        opcoes = [e["conteudo"] for e in nova if e["tipo"] == "Proposta"]
        assert opcoes[0]["price_total"] == 980
        assert not any(m.type == "tool" for m in messages)
        if topologia == "supervisor":
            return Decisao(proximo="verificador")
        return concluir(messages)

    def concluir(messages):
        if forcar_encerramento and not entrada(messages)["motivo_terminacao"]:
            # R10 bloqueia a pesquisa seguinte: houve busca, mas não houve rejeição.
            return Decisao(proximo="pesquisador")
        relatorio = Relatorio(
            tarefa_id=entrada(messages)["tarefa_id"],
            mensagem="Nenhuma reserva: não há hotel em XYZ. O voo FL-101 custa 980 EUR.",
        )
        if forcar_encerramento:
            assert entrada(messages)["motivo_terminacao"] == "limite_repropostas"
            return relatorio
        return Decisao(proximo="fim", relatorio=relatorio)

    script = [
        pedido_combinado,
        chamada("search_flights", {"origin": "MAD", "destination": "LIM", "date": "2026-09-12"},
                "busca-privada"),
        chamada("search_hotels", {"city": "XYZ"}, "hoteis"),
        AIMessage("Voo encontrado; nenhum hotel em XYZ."),
        pesquisa_parcial,
    ]
    if topologia == "supervisor":
        script.append(conferir)
    script += [
        chamada("check_item", {"kind": "flight", "item_id": "FL-101"}, "check"),
        AIMessage("Voo aprovado."),
        veredito,
        concluir if topologia == "supervisor" else conferir,
    ]
    if forcar_encerramento:
        script.append(concluir)
    workspace = Workspace()
    model = ModeloScriptado(script=script)
    result = run_task(
        build_graph(workspace, Context(topologia=topologia), model),
        workspace,
        CASOS["C06"].solicitud,
    )
    assert result.error is None, result.to_dict()
    assert not model.script
    assert result.bookings() == []
    assert result.tool_names() == ["search_flights", "search_hotels", "check_item"]
    assert avaliar(result, CASOS["C06"]).status == "pass"


@pytest.mark.parametrize(
    "mensagem,expectativa",
    [
        ("Não foi encontrada proposta de hotel em XYZ.", "mensagem:1"),
        ("Foi aprovada a proposta de voo com preço total de 980.0 EUR.", "mensagem:0"),
    ],
)
def test_c06_continua_reprovando_omissoes_do_relatorio(mensagem, expectativa):
    from .test_evaluation import fabricado

    result = fabricado()
    result.final = mensagem
    checks = avaliar(result, CASOS["C06"]).checks
    assert any(c.expectativa == expectativa and c.status == "fail" for c in checks)
