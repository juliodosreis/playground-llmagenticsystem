import pytest


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    monkeypatch.delenv("TRAVEL_DEFEITOS", raising=False)
    monkeypatch.setenv("TRAVEL_TOPOLOGIA", "workflow")

    def bloquear(_):
        raise AssertionError("teste tentou carregar um provedor externo")

    for modulo in (
        "travel_mas.agents.mas.graph",
        "travel_mas.interfaces.a2a.servidor",
        "travel_mas.interfaces.a2a.agente_cliente",
    ):
        monkeypatch.setattr(f"{modulo}.load_chat_model", bloquear)
    monkeypatch.setattr("travel_mas.cli.load_dotenv", lambda *args: None)
