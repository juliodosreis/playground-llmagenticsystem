"""Carga do cliente do provedor Groq a partir do `Context`, sem chamada de rede."""

import pytest

from travel_mas import Context
from travel_mas.runtime.models import load_chat_model, without_reasoning


def test_groq_usa_gpt_oss_120b_por_padrao(monkeypatch):
    monkeypatch.delenv("TRAVEL_MODEL", raising=False)
    assert Context(provider="groq").model == "openai/gpt-oss-120b"


def test_groq_sem_chave_levanta_runtime_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        load_chat_model(Context(provider="groq"))


def test_groq_recebe_nivel_de_raciocinio_limites_e_reintentos(monkeypatch):
    chat_groq = pytest.importorskip("langchain_groq").ChatGroq
    monkeypatch.setenv("GROQ_API_KEY", "gsk-teste")
    monkeypatch.delenv("TRAVEL_MODEL", raising=False)
    context = Context(provider="groq", max_tokens=900, request_timeout=30.0, retry_attempts=4)
    model = load_chat_model(context)
    assert isinstance(model, chat_groq)
    assert model.model_name == "openai/gpt-oss-120b"
    assert model.reasoning_effort == "low"
    # O ChatGroq troca temperature=0 por 1e-08, o menor valor que a API do Groq aceita.
    assert model.temperature < 1e-6
    assert (model.max_tokens, model.request_timeout) == (900, 30.0)
    assert model.max_retries == 3
    assert model.groq_api_key.get_secret_value() == "gsk-teste"
    assert without_reasoning(model) is model


def test_provedor_desconhecido_lista_groq():
    with pytest.raises(ValueError, match="groq"):
        load_chat_model(Context(provider="outro"))


def erro_groq(codigo):
    groq = pytest.importorskip("groq")
    import httpx

    resposta = httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com"))
    corpo = {
        "error": {"message": "parameters for tool Relatorio did not match schema", "code": codigo}
    }
    return groq.BadRequestError("Error code: 400", response=resposta, body=corpo)


def test_preencher_reintenta_esquema_recusado_pelo_groq():
    import asyncio

    from langchain_core.messages import HumanMessage
    from langchain_core.runnables import RunnableLambda

    from travel_mas.agents.mas.contracts import Relatorio
    from travel_mas.runtime.structured import preencher

    recebidas = []

    def responder(mensagens):
        recebidas.append(mensagens)
        if len(recebidas) == 1:
            raise erro_groq("tool_use_failed")
        return {"tarefa_id": "t", "mensagem": "ok"}

    resultado = asyncio.run(preencher(RunnableLambda(responder), [HumanMessage("x")], Relatorio))
    assert resultado.mensagem == "ok"
    assert "did not match schema" in recebidas[1][-1].content


def test_preencher_propaga_outro_erro_400_do_groq():
    import asyncio

    from langchain_core.messages import HumanMessage
    from langchain_core.runnables import RunnableLambda

    from travel_mas.agents.mas.contracts import Relatorio
    from travel_mas.runtime.structured import preencher

    erro = erro_groq("context_length_exceeded")

    def responder(_):
        raise erro

    with pytest.raises(type(erro)):
        asyncio.run(preencher(RunnableLambda(responder), [HumanMessage("x")], Relatorio))


def test_groq_envia_reasoning_effort_so_a_modelo_que_raciocina(monkeypatch):
    pytest.importorskip("langchain_groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-teste")
    assert load_chat_model(Context(provider="groq", model="openai/gpt-oss-20b")).reasoning_effort
    assert load_chat_model(Context(provider="groq", model="qwen/qwen3.8-27b")).reasoning_effort
    # allam-2-7b responde 400 "`reasoning_effort` is not supported with this model".
    assert load_chat_model(Context(provider="groq", model="allam-2-7b")).reasoning_effort is None


def test_pensar_reintenta_chamada_de_ferramenta_recusada_pelo_groq():
    """O Groq recusa no servidor argumentos fora do esquema; o modelo recebe o motivo."""
    import asyncio

    from langchain_core.messages import AIMessage, HumanMessage

    from travel_mas import Workspace
    from travel_mas.agents.mas.contracts import ResultadoPesquisa
    from travel_mas.agents.mas.pesquisador.graph import build_graph as pesquisador
    from travel_mas.tools import build_toolbox

    from .test_mas import ModeloScriptado, chamada

    def recusar(_):
        raise erro_groq("tool_use_failed")

    def corrigir(mensagens):
        assert "did not match schema" in mensagens[-1].content
        busca = {"origin": "MAD", "destination": "LIM", "date": "2026-09-12"}
        return chamada("search_flights", busca, "busca")

    model = ModeloScriptado(
        script=[recusar, corrigir, AIMessage("ok"), ResultadoPesquisa(propostas=[], motivo="x")]
    )
    workspace = Workspace()
    agente = pesquisador(model, build_toolbox(workspace), Context())
    final = asyncio.run(agente.ainvoke({"messages": [HumanMessage("{}")], "passos": 0}))
    assert [c.name for c in workspace.trace] == ["search_flights"]
    assert final["saida"]["motivo"] == "x"
    # O aviso de recusa vai só na chamada repetida e não entra no histórico do papel.
    assert not any("did not match schema" in str(m.content) for m in final["messages"])
