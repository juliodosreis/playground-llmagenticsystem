"""Planejamento de tandas sem carregar configuração nem chamar o provedor."""

import runpy
from pathlib import Path

import pytest


@pytest.fixture
def tanda(monkeypatch):
    def bloquear(*args, **kwargs):
        raise AssertionError("planejamento tentou ler configuração de provedor")

    monkeypatch.setattr("dotenv.load_dotenv", bloquear)
    return runpy.run_path(str(Path("reports/scripts/tanda.py")))["main"]


def test_tanda_sem_autorizacao_so_imprime_plano(tanda, tmp_path, capsys):
    output = tmp_path / "nova"
    assert tanda([str(output), "--casos", "C06", "--k", "3"]) == 0
    assert "total=6" in capsys.readouterr().out
    assert not output.exists()


@pytest.mark.parametrize("existente", [False, True])
def test_tanda_recusa_excesso_e_sobrescrita_antes_de_carregar_provedor(tanda, tmp_path, existente):
    output = tmp_path / "nova"
    args = [str(output), "--casos", "C06", "--autorizar-provedor"]
    if existente:
        output.mkdir()
        evidencia = output / "evidencia.json"
        evidencia.write_text("original")
    else:
        args += ["--k", "4"]
    with pytest.raises(SystemExit) as exc:
        tanda(args)
    assert exc.value.code == 2
    if existente:
        assert evidencia.read_text() == "original"
    else:
        assert not output.exists()
