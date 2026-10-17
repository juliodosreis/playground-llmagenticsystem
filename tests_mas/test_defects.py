"""Defeitos exercitam o grafo real; decisões dos papéis são controladas, sem LLM."""

import json
from collections import Counter

import pytest

from travel_mas import Context, Workspace, build_graph, run_task
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
from travel_mas.agents.mas.graph import AGENTES
from travel_mas.domain import operations
from travel_mas.evaluation.casos import CASOS
from travel_mas.evaluation.checks import avaliar
from travel_mas.runtime.workspace import chamada_atual


def papeis(monkeypatch, workspace, modo="aprovar"):
    counts = Counter()

    class Papel:
        def __init__(self, nome, esquema):
            self.nome = nome
            self.esquema = esquema

        async def ainvoke(self, state, config=None):
            # O histórico privado traz as entradas anteriores; cada uma tem só a parte nova.
            entradas = [json.loads(m.content) for m in state["messages"]]
            entrada = entradas[-1]
            bandeja = [e for x in entradas for e in x["bandeja"]]
            counts[self.nome] += 1

            def mensagens(tipo):
                return [e["conteudo"] for e in bandeja if e["tipo"] == tipo]

            if self.nome == "coordenador":
                task = entrada["tarefa_id"]
                propostas = mensagens("Proposta")
                vereditos = mensagens("Veredito")
                if (
                    entrada.get("motivo_terminacao")
                    or mensagens("Relatorio")
                    or "clima" in entrada["pedido_usuario"]
                ):
                    output = Decisao(
                        proximo="fim",
                        relatorio=Relatorio(
                            tarefa_id=task, mensagem="Apenas reservas. Menor preço: 980 EUR."
                        ),
                    )
                elif not bandeja:
                    output = Decisao(
                        proximo="pesquisador",
                        pedido=Pedido(
                            tarefa_id=task,
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
                else:
                    p = propostas[-1]
                    v = next(
                        (v for v in reversed(vereditos) if v["proposta_id"] == p["proposta_id"]),
                        None,
                    )
                    if v is None:
                        output = Decisao(proximo="verificador")
                    elif not v["aprovado"]:
                        output = Decisao(
                            proximo="fim",
                            relatorio=Relatorio(
                                tarefa_id=task, mensagem="Menor preço 980 EUR, sem reserva."
                            ),
                        )
                    else:
                        output = Decisao(
                            proximo="reservador",
                            ordens=[
                                Ordem(tarefa_id=task, proposta_id=p["proposta_id"], user_id="u-42")
                            ],
                        )
            elif self.nome == "pesquisador":
                pedido = mensagens("Pedido")[-1]
                id_busca = f"busca-{counts[self.nome]}"
                token = chamada_atual.set(id_busca)
                try:
                    workspace.call(
                        operations.search_flights,
                        origin="MAD",
                        destination="LIM",
                        date="2026-09-12",
                    )
                finally:
                    chamada_atual.reset(token)
                output = ResultadoPesquisa(
                    propostas=[
                        Proposta(
                            tarefa_id=pedido["tarefa_id"],
                            proposta_id=f"p{counts[self.nome]}",
                            kind="flight",
                            item_id="FL-101",
                            price_total=980,
                            date="2026-09-12",
                            evidencia=id_busca,
                        )
                    ]
                )
            elif self.nome == "verificador":
                p = mensagens("Proposta")[-1]
                workspace.call(operations.check_item, kind="flight", item_id="FL-101")
                aprovado = modo == "aprovar" or (modo == "revisar" and counts[self.nome] > 1)
                output = ResultadoVerificacao(
                    vereditos=[
                        Veredito(
                            tarefa_id=p["tarefa_id"],
                            proposta_id=p["proposta_id"],
                            aprovado=aprovado,
                            motivo="teste",
                        )
                    ]
                )
            else:
                ordem = mensagens("Ordem")[-1]
                props = mensagens("Proposta")
                p = next((p for p in props if p["proposta_id"] == ordem["proposta_id"]), None)
                ids = []
                if p:
                    result = json.loads(
                        workspace.call(
                            operations.create_booking,
                            user_id=ordem["user_id"],
                            kind=p["kind"],
                            item_id=p["item_id"],
                            start_date=p["date"],
                            price=p["price_total"],
                        )
                    )
                    ids.append(result["booking_id"])
                output = Relatorio(
                    tarefa_id=ordem["tarefa_id"],
                    booking_ids=ids,
                    mensagem="concluído" if ids else "proposta não corresponde",
                )
            if self.esquema is Relatorio and isinstance(output, Decisao):
                output = output.relatorio
            return {"saida": output.model_dump(mode="json"), "passos": 0}

    for nome in AGENTES:

        def montar(model, toolbox, context, nome=nome, esquema=None):
            return Papel(nome, esquema)

        monkeypatch.setitem(AGENTES, nome, montar)
    return counts


@pytest.mark.parametrize("defeito", ["D1", "D2", "D3", "D4", "D5", "D6"])
def test_defeito_e_codigo_e_emite_ativacao(monkeypatch, defeito):
    workspace = Workspace()
    modo = "revisar" if defeito == "D5" else "rejeitar" if defeito in ("D3", "D6") else "aprovar"
    counts = papeis(monkeypatch, workspace, modo)
    context = Context(defeitos=(defeito,), max_rodadas=4 if defeito == "D6" else 12)
    result = run_task(
        build_graph(workspace, context, object()),
        workspace,
        CASOS["C01"].solicitud,
        recursion_limit=12,
    )
    assert any(e["tipo"] == "injection_applied" and e["id"] == defeito for e in result.eventos)
    if defeito in ("D1", "D2"):
        assert counts["verificador"] == 0
        assert not any(c.name == "check_item" for c in result.trace)
    if defeito == "D3":
        assert result.bookings() and any(c.name == "create_booking" for c in result.trace)
        assert avaliar(result, CASOS["C04"]).status == "fail"
    if defeito == "D4":
        assert result.bookings()[0]["user_id"] != "u-42"
        assert avaliar(result, CASOS["C01"]).status == "fail"
    if defeito == "D5":
        assert not result.bookings()
        recebidas = [
            e["conteudo"]["proposta_id"]
            for e in result.bitacora
            if e["para"] == "reservador" and e["mensagem_tipo"] == "Proposta"
        ]
        assert recebidas == ["p1"]
    if defeito == "D6":
        assert counts["pesquisador"] > 2
        failed = [c for c in avaliar(result, CASOS["C04"]).checks if c.status == "fail"]
        assert any(c.regra_origem.endswith("R10") for c in failed)


@pytest.mark.parametrize("topologia", ["workflow", "supervisor"])
@pytest.mark.parametrize("defeito", ["D1", "D2", "D3", "D4", "D5", "D6"])
def test_defeito_nao_acionado_nao_reprova_pedido_fora_do_escopo(monkeypatch, topologia, defeito):
    workspace = Workspace()
    papeis(monkeypatch, workspace)
    context = Context(topologia=topologia, defeitos=(defeito,))
    result = run_task(build_graph(workspace, context, object()), workspace, CASOS["C11"].solicitud)
    assert not any(e["tipo"] == "injection_applied" for e in result.eventos)
    assert avaliar(result, CASOS["C11"]).status == "pass"
