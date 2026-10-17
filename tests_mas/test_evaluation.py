import asyncio
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from travel_mas import Context, RunResult, Workspace, build_graph, run_task
from travel_mas.agents.mas.graph import AGENTES, entregar
from travel_mas.cli import main
from travel_mas.domain import TravelDB, operations
from travel_mas.evaluation.casos import CASOS, Caso, Expectativa, evento, origem, validate_case
from travel_mas.evaluation.checks import avaliar
from travel_mas.evaluation.suite import CaseRun, arun_case, summary
from travel_mas.evaluation.validation import detectou, exigir_ativacao, reavaliar
from travel_mas.runtime.faults import MessageFault, ToolFault, capabilities

from .test_mas import ModeloScriptado, script_reserva


def fabricado(eventos=None, **kwargs):
    state = Workspace().snapshot()
    eventos = eventos or [{"seq": 1, "tipo": "termination", "agente": "coordenador"}]
    return RunResult(
        prompt="x",
        before=state,
        after=deepcopy(state),
        trace=[],
        final="fim",
        values={"tarefa_id": "t", "relatorio": {"tarefa_id": "t"}, "max_rodadas": 12},
        eventos=eventos,
        **kwargs,
    )


PENDENTE = Caso(
    id="TP",
    nome="pendente",
    solicitud="x",
    regra_origem=["R11"],
    expectativa=Expectativa(),
    pendente="decisão de teste",
)


def caso(**kwargs):
    return Caso(
        id="T", nome="teste", solicitud="x", regra_origem=["R11"], expectativa=Expectativa(**kwargs)
    )


def test_oraculo_nao_reprova_fluxo_valido():
    workspace = Workspace()
    model = ModeloScriptado(script=script_reserva("workflow"))
    result = run_task(build_graph(workspace, Context(), model), workspace, CASOS["C01"].solicitud)
    evaluation = avaliar(result, CASOS["C01"])
    assert evaluation.status == "pass", evaluation.to_dict()


def test_hitos_sao_subsequencia_e_proibicao_falha_com_um_evento():
    eventos = [
        {"seq": i + 1, **e}
        for i, e in enumerate(
            [
                {"tipo": "agent_start", "agente": "pesquisador"},
                {"tipo": "agent_end", "agente": "pesquisador"},
                {"tipo": "termination", "agente": "coordenador"},
            ]
        )
    ]
    expected = caso(hitos=[evento("R11", tipo="agent_start"), evento("R11", tipo="termination")])
    assert avaliar(fabricado(eventos), expected).status == "pass"
    expected.expectativa.hitos.reverse()
    assert avaliar(fabricado(eventos), expected).status == "fail"
    expected = caso(prohibiciones=[evento("R11", tipo="agent_end")])
    assert avaliar(fabricado(eventos), expected).status == "fail"


def test_injecao_nao_ativada_nunca_aprova():
    evaluation = avaliar(fabricado(), CASOS["C12"])
    assert evaluation.status == "no_activado"
    assert all(c.regra_origem for c in evaluation.checks)


def test_pendente_e_capacidade_ausente_sao_nao_avaliaveis():
    assert avaliar(fabricado(), PENDENTE).status == "no_evaluable"
    unsupported = caso(hitos=[evento("R11", tipo="evento_inexistente")])
    assert avaliar(fabricado(), unsupported).status == "no_evaluable"
    unavailable = caso(
        estado_final=[{"tabela": "hotels", "linhas": [], "regra_origem": origem("R2")}]
    )
    assert avaliar(fabricado(), unavailable).status == "no_evaluable"


def test_estado_nao_ignora_linhas_extras_nem_duplicatas():
    result = fabricado()
    result.after["bookings"] = [{"id": "1", "item_id": "a"}, {"id": "2", "item_id": "a"}]
    expected = caso(
        estado_final=[
            {"tabela": "bookings", "linhas": [{"item_id": "a"}], "regra_origem": origem("R7")}
        ]
    )
    assert avaliar(result, expected).status == "fail"


def test_pass_k_exige_todas_as_repeticoes_e_exclui_nao_avaliaveis():
    result = fabricado()
    ok = avaliar(result, caso())
    bad = avaliar(result, caso(prohibiciones=[evento("R11", tipo="termination")]))
    config = {"topologia": "workflow", "defeitos": []}
    rows = summary(
        [
            CaseRun("T", 1, config, ok, result),
            CaseRun("T", 2, config, bad, result),
            CaseRun("TP", 1, config, avaliar(result, PENDENTE), result),
        ]
    )
    assert rows["pass^k"] == 0 and rows["nao_avaliaveis"] == 1
    assert rows["casos"][0]["pass"] == 1


def test_todos_os_casos_tem_expectativas_e_origem():
    assert {f"C{i:02}" for i in range(1, 15)} <= CASOS.keys()
    for c in CASOS.values():
        validate_case(c)
        assert c.regra_origem
    assert capabilities()["defeitos"] == [f"D{i}" for i in range(1, 7)]


def test_estado_inicial_e_reset_atomico():
    workspace = Workspace()
    workspace.reset(CASOS["C09"].estado_inicial)
    assert workspace.snapshot()["bookings"][0]["user_id"] == "u-42"
    antes = workspace.snapshot()
    with pytest.raises(ValueError):
        workspace.reset({"tabela_sql_invalida": []})
    assert workspace.snapshot() == antes
    workspace.reset()
    assert workspace.snapshot()["bookings"] == []
    with pytest.raises(ValueError):
        TravelDB({"flights": [{"id": "incompleto"}]})


@pytest.mark.parametrize("tipo", ["error", "timeout", "vazia", "inconsistente"])
def test_falha_de_ferramenta_nao_executa_escrita(tipo):
    workspace = Workspace(tool_faults=[ToolFault(id="falha", tool="create_booking", tipo=tipo)])
    workspace.reset()
    antes = workspace.snapshot()
    workspace.call(
        operations.create_booking,
        user_id="u",
        kind="flight",
        item_id="FL-101",
        start_date="2026-09-12",
        price=980,
    )
    assert workspace.snapshot() == antes
    assert any(e["tipo"] == "injection_applied" and e["id"] == "falha" for e in workspace.eventos)
    assert workspace.eventos[-1]["executada"] is False


def test_ordem_de_chamada_e_falha_persistente_reiniciam_no_reset():
    workspace = Workspace(tool_faults=[ToolFault(id="f", tool="search_flights", tipo="timeout")])
    workspace.reset()
    for _ in range(2):
        first = json.loads(
            workspace.call(
                operations.search_flights, origin="MAD", destination="LIM", date="2026-09-12"
            )
        )
        second = json.loads(
            workspace.call(
                operations.search_flights, origin="MAD", destination="LIM", date="2026-09-12"
            )
        )
        assert first["error"] == "timeout" and second[0]["id"] == "FL-101"
        workspace.reset()


@pytest.mark.parametrize("tipo", ["campo_faltante", "obsoleta", "de_outra_tarefa", "perdida"])
def test_falhas_de_mensagem_preservam_original_na_bitacora(tipo):
    from travel_mas.agents.mas.contracts import Proposta

    workspace = Workspace(
        message_faults=[
            MessageFault(
                id="f",
                aresta="pesquisador->verificador",
                tipo=tipo,
            )
        ]
    )
    workspace.reset()
    state = {"bandejas": {nome: [] for nome in AGENTES}, "bitacora": []}
    p = Proposta(
        tarefa_id="t",
        proposta_id="p",
        kind="flight",
        item_id="FL-101",
        price_total=980,
        date="2026-09-12",
        evidencia="busca",
    )
    entregar("pesquisador", "verificador", p, state=state, workspace=workspace)
    assert state["bitacora"][0]["conteudo"] == p.model_dump()
    received = state["bitacora"][0]["recebido"]
    assert received != p.model_dump()
    assert any(e["tipo"] == "injection_applied" for e in workspace.eventos)
    if tipo == "perdida":
        assert not state["bandejas"]["verificador"]
    elif tipo == "campo_faltante":
        assert "evidencia" not in received


def test_caso_pendente_nao_chama_modelo():
    result = asyncio.run(arun_case(PENDENTE, Context()))
    assert result.resultado is None and result.avaliacao.status == "no_evaluable"


def test_erro_do_provedor_nao_conta_como_deteccao_de_defeito():
    result = fabricado(error="provedor indisponível")
    result.eventos.insert(0, {"seq": 0, "tipo": "injection_applied", "id": "D1"})
    evaluation = avaliar(result, CASOS["C04"])
    assert evaluation.status == "fail"
    run = CaseRun("C04", 1, {"topologia": "workflow", "defeitos": ["D1"]}, evaluation, result)
    assert not detectou(run, "D1")


def test_manifesto_do_adaptador_nao_desalinha():
    spec = yaml.safe_load(Path("spec/mas.yaml").read_text())
    caps = capabilities()
    assert spec["adaptador"]["defeitos"] == caps["defeitos"]
    assert spec["adaptador"]["observacao"] == caps["eventos"]
    assert spec["adaptador"]["falhas_ferramenta"] == caps["condicion_herramienta"]
    assert spec["adaptador"]["falhas_mensagem"] == caps["condicion_transferencia"]
    assert spec["terminacao"]["max_rodadas"] == Context().max_rodadas


def test_cli_descobre_capacidades_e_recusa_caso_desconhecido_sem_llm(capsys):
    assert main(["capabilities"]) == 0
    assert json.loads(capsys.readouterr().out)["defeitos"][-1] == "D6"
    assert main(["casos", "inexistente"]) == 2
    assert "desconhecidos" in capsys.readouterr().err


def test_cli_pendente_exporta_sem_llm_e_sem_sucesso_falso(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(CASOS, "TP", PENDENTE)
    path = tmp_path / "relatorio.json"
    assert main(["casos", "TP", "--k", "3", "--output", str(path)]) == 1
    payload = json.loads(path.read_text())
    assert payload["resumo"]["pass^k"] is None
    assert all(r["avaliacao"]["status"] == "no_evaluable" for r in payload["execucoes"])


def test_timeout_persistente_exige_um_reintento():
    eventos = [
        {"tipo": "tool_call", "ferramenta": "search_flights", "chamada_id": "a", "argumentos": {}},
        {"tipo": "injection_applied", "id": "C12P-timeout"},
        {
            "tipo": "tool_result",
            "ferramenta": "search_flights",
            "chamada_id": "a",
            "resultado": '{"error":"timeout","transient":true}',
        },
        {"tipo": "termination", "agente": "coordenador"},
    ]
    result = fabricado([{**e, "seq": i + 1} for i, e in enumerate(eventos)])
    result.final = "Falha por timeout."
    evaluation = avaliar(result, CASOS["C12P"])
    assert evaluation.status == "fail"
    assert any(c.status == "fail" and c.regra_origem.endswith("R10") for c in evaluation.checks)


def test_replay_reavalia_traca_sem_modelo_e_nao_declara_matriz_parcial_completa(tmp_path):
    workspace = Workspace()
    model = ModeloScriptado(script=script_reserva("workflow"))
    context = Context()
    result = run_task(build_graph(workspace, context, model), workspace, CASOS["C01"].solicitud)
    run = CaseRun("C01", 1, asdict(context), avaliar(result, CASOS["C01"]), result)
    (tmp_path / "referencia-workflow-normal-C01-1.json").write_text(json.dumps(run.to_dict()))
    payload = reavaliar(tmp_path)
    assert payload["referencia"]["casos"][0]["pass^k"] == 1
    assert payload["matriz_completa"] is False
    assert not any(d["controle_passou"] for d in payload["defeitos"])
    assert not model.script


def test_dado_inconsistente_de_ferramenta_nao_quebra_o_avaliador():
    eventos = [
        {
            "tipo": "tool_result",
            "ferramenta": "search_hotels",
            "chamada_id": "busca",
            "resultado": json.dumps([{"id": "HT-2", "price_per_night": {"invalido": True}}]),
        },
        {
            "tipo": "handoff",
            "de": "pesquisador",
            "para": "verificador",
            "mensagem_tipo": "Proposta",
            "conteudo": {
                "tarefa_id": "t",
                "proposta_id": "p",
                "kind": "hotel",
                "item_id": "HT-2",
                "date": "2026-09-12",
                "price_total": 135,
                "noites": 3,
                "evidencia": "busca",
            },
        },
        {"tipo": "termination", "agente": "coordenador"},
    ]
    result = fabricado([{**e, "seq": i + 1} for i, e in enumerate(eventos)])
    evaluation = avaliar(result, CASOS["C07"])
    assert evaluation.status == "fail"
    assert any(c.status == "fail" and c.regra_origem.endswith("R2") for c in evaluation.checks)


def test_alvo_sem_ativacao_nao_conta_como_pass_mas_controle_permanece_normal():
    result = fabricado()
    result.final = "Menor preço 980 EUR."
    evaluation = avaliar(result, CASOS["C04"])
    assert evaluation.status == "pass"
    run = CaseRun("C04", 1, {"defeitos": ["D3"]}, evaluation, result)
    exigir_ativacao(run)
    assert run.avaliacao.status == "no_activado"


def test_cli_combina_defeitos_antes_e_depois_do_subcomando(monkeypatch):
    capturado = []

    def capturar(args):
        capturado.append(args.context.defeitos)
        return 0

    monkeypatch.setattr("travel_mas.cli.command_cases", capturar)
    assert main(["--defeito", "D3", "casos", "C03", "--defeito", "D1", "--defeito", "D3"]) == 0
    assert capturado == [("D1", "D3")]


@pytest.mark.parametrize("key", ["C09", "C10"])
def test_oraculo_exige_reserva_previa_em_vez_de_aceitar_banco_vazio_inalterado(key):
    result = fabricado()
    assert avaliar(result, CASOS[key]).status == "fail"


def test_r2_reprova_id_ausente_da_busca_uma_vez_por_proposta():
    # A evidencia aponta para a busca certa, mas o item_id não está entre as linhas retornadas.
    linha = {"id": "FL-101", "price": 980.0, "date": "2026-09-12", "seats": 4}

    def proposta(pid, item, para):
        conteudo = {
            "tarefa_id": "t",
            "proposta_id": pid,
            "kind": "flight",
            "item_id": item,
            "price_total": 980.0,
            "date": "2026-09-12",
            "evidencia": "b",
            "noites": 1,
        }
        return {
            "tipo": "handoff",
            "de": "pesquisador",
            "para": para,
            "mensagem_tipo": "Proposta",
            "conteudo": conteudo,
            "recebido": conteudo,
            "entregue": True,
        }

    eventos = [
        {"tipo": "tool_call", "agente": "pesquisador", "ferramenta": "search_flights",
         "chamada_id": "b", "argumentos": {}},
        {"tipo": "tool_result", "agente": "pesquisador", "ferramenta": "search_flights",
         "chamada_id": "b", "resultado": json.dumps([linha]), "executada": True},
        proposta("p1", "item-1", "verificador"),
        proposta("p1", "item-1", "coordenador"),
        proposta("p2", "FL-101", "verificador"),
        {"tipo": "termination", "agente": "coordenador"},
    ]
    eventos = [{"seq": i + 1, **e} for i, e in enumerate(eventos)]
    caso_r2 = Caso(
        id="T", nome="r2", solicitud="x", regra_origem=["R2"], expectativa=Expectativa()
    )
    r2 = next(c for c in avaliar(fabricado(eventos), caso_r2).checks if c.expectativa == "R2")
    assert r2.status == "fail"
    assert r2.detalhe == "proposta p1 sem evidência de busca"


def test_esquema_da_proposta_descreve_item_id_e_evidencia():
    from travel_mas.agents.mas.contracts import ResultadoPesquisa

    texto = json.dumps(ResultadoPesquisa.model_json_schema(), ensure_ascii=False)
    assert "campo id de uma linha da busca" in texto
    assert "campo evidencia do retorno da busca" in texto
