"""Planejamento de tandas sem carregar configuração nem chamar o provedor."""

import json
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


def _script(nome):
    return runpy.run_path(str(Path(f"reports/scripts/{nome}.py")))["main"]


def _traca(path, status, item_id):
    path.write_text(json.dumps({
        "avaliacao": {"status": status, "checks": [
            {"expectativa": "R2", "status": status, "regra_origem": "R2",
             "detalhe": "sem evidência" if status == "fail" else ""},
        ]},
        "resultado": {"eventos": [
            {"seq": 1, "tipo": "agent_end", "agente": "pesquisador",
             "saida": {"propostas": [{"item_id": item_id}]}},
        ]},
    }))


def test_resumo_ignora_arquivos_sem_avaliacao(tmp_path, capsys):
    _traca(tmp_path / "referencia-workflow-normal-C01-1.json", "fail", "FL-101")
    (tmp_path / "manifest.json").write_text(json.dumps({"commit": "x"}))
    (tmp_path / "summary.json").write_text(json.dumps({"referencia": {}}))
    assert _script("resumo")(sorted(str(p) for p in tmp_path.glob("*.json"))) == 0
    saida = capsys.readouterr().out.splitlines()
    assert saida == ["referencia-workflow-normal-C01-1.json: fail  R2[R2]:sem evidência"]


def test_ids_conta_os_diretorios_recebidos(tmp_path, capsys):
    diretorio = tmp_path / "medicao"
    diretorio.mkdir()
    _traca(diretorio / "a.json", "pass", "FL-101")
    _traca(diretorio / "b.json", "pass", "item-1")
    (diretorio / "manifest.json").write_text(json.dumps({"commit": "x"}))
    assert _script("ids")([str(diretorio)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "('medicao', False) 1",
        "('medicao', True) 1",
        "medicao [('b.json', 'item-1')]",
    ]
