import pytest


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    monkeypatch.delenv("TRAVEL_DEFEITOS", raising=False)
    monkeypatch.setenv("TRAVEL_TOPOLOGIA", "workflow")

    def bloquear(_):
        raise AssertionError("teste tentou carregar um provedor externo")

    monkeypatch.setattr("travel_mas.agents.mas.graph.load_chat_model", bloquear)
    monkeypatch.setattr("travel_mas.cli.load_dotenv", lambda *args: None)
