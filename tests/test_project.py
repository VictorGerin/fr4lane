"""fr4lane.json: o projeto que usa o fr4lane (fontes, testbench, floorplan, saída)."""

import json
import re
import shutil

import pytest

from conftest import data, run_flow
from fr4lane import project
from fr4lane.project import ProjectError


@pytest.fixture
def root(tmp_path):
    for f in ("rtl/top.v", "rtl/sub/m.v", "rtl/sva/props.v", "rtl/x.sv", "sim/tb_top.v",
              "rtl/sub/top.floorplan.json"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("", encoding="utf-8")
    cfg = {"src": ["rtl/**/*.v", "rtl/**/*.sv"], "exclude": ["rtl/sva/*"], "tb": "sim/tb_{top}.v",
           "floorplan": ["rtl/**/{top}.floorplan.json"], "out": "saida"}
    (tmp_path / "fr4lane.json").write_text(json.dumps(cfg), encoding="utf-8")
    return tmp_path


def test_le_o_projeto(root):
    p = project.load(root / "fr4lane.json")
    assert [p.rel(f) for f in p.sources()] == ["rtl/sub/m.v", "rtl/top.v", "rtl/x.sv"]   # sem rtl/sva
    assert p.rel(p.testbench("top")) == "sim/tb_top.v" and p.testbench("outro") is None
    assert p.rel(p.find_floorplan("top")) == "rtl/sub/top.floorplan.json" and p.find_floorplan("m") is None
    assert p.out_dir("top_cmos") == root / "saida" / "top_cmos"


def test_procura_o_fr4lane_json_nas_pastas_de_cima(root):
    assert project.find(root / "rtl" / "sub").root == root
    assert project.find(root / "rtl" / "top.v").config == root / "fr4lane.json"


def test_sem_fr4lane_json(tmp_path):
    p = project.find(tmp_path)
    assert p.root == tmp_path and p.config is None and p.sources() == [] and p.testbench("x") is None
    assert p.out_dir("t") == tmp_path / "build" / "pcb" / "t"


@pytest.mark.parametrize("cfg, msg", [
    ({"fontes": []}, "chave(s) desconhecida(s)"),
    ({"src": [1]}, "'src' deve ser"),
    ({"tb": ["a"]}, "'tb' deve ser um texto"),
    ({"out": ""}, "'out' deve ser uma pasta"),
    ([], "esperado um objeto"),
])
def test_recusa(tmp_path, cfg, msg):
    f = tmp_path / "fr4lane.json"
    f.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(ProjectError, match=re.escape(msg)):
        project.load(f)


@pytest.mark.slow
def test_fluxo_usa_o_fr4lane_json(tmp_path):
    """fr4lane --top hier8 dentro do projeto: fontes, testbench e floorplan vêm do
    fr4lane.json e a rodada vai para a pasta 'out' dele."""
    (tmp_path / "rtl").mkdir()
    (tmp_path / "sim").mkdir()
    shutil.copy(data("hier8.v"), tmp_path / "rtl")
    shutil.copy(data("tb_hier8.v"), tmp_path / "sim")
    (tmp_path / "rtl" / "hier8.floorplan.json").write_text(
        json.dumps({"modules": {"lo": {"type": "region", "rect": [20, 10, 400, 200]}}}), encoding="utf-8")
    (tmp_path / "fr4lane.json").write_text(json.dumps({
        "src": ["rtl/*.v"], "tb": "sim/tb_{top}.v", "floorplan": ["rtl/{top}.floorplan.json"],
        "out": "placas"}), encoding="utf-8")
    r = run_flow(None, "--top", "hier8", "--lib", "rtl", "--synth-only", cwd=tmp_path / "rtl")   # de uma subpasta
    assert r.rc == 0, r
    assert "Testbench do projeto: sim/tb_hier8.v" in r.log and "Floorplan do projeto: rtl/hier8.floorplan.json" in r.log
    assert re.search(r"gate-level:\s+OK", r.log) and re.search(r"componentes:\s+OK", r.log), r
    assert (tmp_path / "placas" / "hier8_rtl" / "placement.json").is_file()
    # --no-tb e --no-floorplan desligam o que vem do projeto
    r = run_flow(None, "--top", "hier8", "--lib", "rtl", "--synth-only", "--no-tb", "--no-floorplan", cwd=tmp_path)
    assert r.rc == 0 and "Testbench do projeto" not in r.log and "Simulação: pulada" in r.log, r


@pytest.mark.slow
def test_fluxo_sem_fontes(tmp_path):
    r = run_flow(None, "--top", "x", cwd=tmp_path)
    assert r.rc == 3 and "sem fontes" in r.log, r
