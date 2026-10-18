"""Fluxo completo (python -m pcbflow) em projetos pequenos: síntese, simulação
gate-level e de componentes, placement, roteamento, verificação e arquivos do
KiCad; latches; macros; reaproveitamento do placement; erros de entrada."""

import json
import re
import shutil

import pytest

from conftest import FAMILIES, PCBFLOW, data, lib_path, run_flow
from pcbflow import fpedit

pytestmark = pytest.mark.slow

COUNTER = ["--top", "counter4", "--src", PCBFLOW / "examples/counter4.v",
           "--tb", PCBFLOW / "examples/tb_counter4.v", "--no-drc"]
HIER = ["--top", "hier8", "--src", data("hier8.v"), "--lib", lib_path("rtl"), "--no-drc"]


def sims_ok(r):
    assert re.search(r"gate-level:\s+OK", r.log), r
    assert re.search(r"componentes:\s+OK", r.log), r


def routed_ok(r):
    assert r.rc == 0, r
    assert re.search(r"violações de folga: 0\b", r.log), r
    assert re.search(r"nets incompletas: 0\b", r.log), r


# ----------------------------------------------------------- placa completa
@pytest.mark.parametrize("family", FAMILIES)
def test_counter4_placa_completa(flow, family):
    r = flow(f"c4_{family}", *COUNTER, "--lib", lib_path(family), "--fresh")
    routed_ok(r)
    sims_ok(r)
    for f in ("counter4_{}.kicad_pcb", "counter4_{}.kicad_pro", "counter4_{}_bom.csv"):
        assert r.file(f.format(family)).is_file(), f
    rep = r.file("report.md").read_text(encoding="utf-8")
    assert "Nenhuma: todas as nets roteadas" in rep
    pcb = r.file(f"counter4_{family}.kicad_pcb").read_text(encoding="utf-8")
    assert pcb.startswith("(kicad_pcb") and "(segment" in pcb and "(footprint" in pcb


def test_counter4_duas_camadas(flow):
    r = flow("c4_cmos_2l", *COUNTER, "--lib", lib_path("cmos"), "--layers", "2", "--fresh")
    routed_ok(r)
    pcb = next(r.out.glob("*.kicad_pcb")).read_text(encoding="utf-8")
    layers = pcb.split("(layers", 1)[1].split("(setup", 1)[0]
    assert '"F.Cu" signal' in layers and '"B.Cu" signal' in layers and "In1.Cu" not in layers
    assert "(zone" not in pcb                      # sem planos: a alimentação é cobre desenhado


def test_quatro_camadas_tem_planos(flow):
    r = flow("c4_cmos", *COUNTER, "--lib", lib_path("cmos"), "--fresh")
    pcb = next(r.out.glob("*.kicad_pcb")).read_text(encoding="utf-8")
    assert '"In1.Cu"' in pcb and '"In2.Cu"' in pcb and pcb.count("(zone") == 2


def test_placement_json_para_o_editor(flow):
    r = flow("c4_cmos", *COUNTER, "--lib", lib_path("cmos"), "--fresh")
    p = r.placement()
    assert p["top"] == "counter4" and p["family"] == "cmos" and p["placed"] is True
    assert p["footprints"] and {"geo", "module_width", "module_types", "board"} <= set(p)


def test_reaproveita_o_placement(flow, tmp_path):
    out = tmp_path / "c4"
    first = run_flow(out, *COUNTER, "--lib", lib_path("cmos"))
    second = run_flow(out, *COUNTER, "--lib", lib_path("cmos"))
    routed_ok(first)
    routed_ok(second)
    assert "reaproveitados" in second.log and "Simulação: já feita" in second.log
    assert second.placement()["footprints"] == first.placement()["footprints"]


def test_placement_deterministico(tmp_path):
    a = run_flow(tmp_path / "a", *HIER, "--place-only", "--fresh")
    b = run_flow(tmp_path / "b", *HIER, "--place-only", "--fresh")
    assert a.rc == b.rc == 0, a
    assert a.placement()["footprints"] == b.placement()["footprints"]


# --------------------------------------------------------------- simulação
@pytest.mark.parametrize("family", FAMILIES)
def test_latches_sintetizados_e_simulados(flow, family):
    r = flow(f"latch_{family}", "--top", "latch_demo", "--src", data("latch_demo.v"),
             "--tb", data("tb_latch_demo.v"), "--lib", lib_path(family), "--synth-only")
    assert r.rc == 0, r
    sims_ok(r)
    stat = r.file("yosys_stat.txt").read_text(encoding="utf-8")
    assert "DLAT" in stat
    assert "$_DLATCH" not in r.file("latch_demo_gates.v").read_text(encoding="utf-8")


def test_testbench_que_falha_aparece(tmp_path):
    tb = tmp_path / "tb_errado.v"
    tb.write_text(data("tb_hier8.v").read_text(encoding="utf-8").replace("a + b + ci)", "a + b + ci + 1)", 1),
                  encoding="utf-8")
    r = run_flow(tmp_path / "out", *HIER, "--tb", tb, "--synth-only")
    assert re.search(r"gate-level:\s+FALHOU", r.log), r
    assert re.search(r"componentes:\s+FALHOU", r.log), r


# ------------------------------------------------------------------ macros
FP_HIER = {"macros": ["add4"],
           "modules": {"hi": {"type": "fence", "rect": [200, 10, 150, 150]}}}


def test_macros_placa_completa(flow):
    r = flow("hier_macros", *HIER, "--tb", data("tb_hier8.v"), "--macro", "fa", "--macro", "add4", "--fresh")
    routed_ok(r)
    sims_ok(r)
    assert "Placement hierárquico (macros: add4, fa)" in r.log
    m = r.placement()["macros"]
    assert set(m["instances"]) >= {"lo", "hi", "lo.f0", "hi.f3"}
    # lo e hi têm a mesma ligação: um molde só, duas cópias
    assert m["instances"]["lo"]["template"] == m["instances"]["hi"]["template"]
    tpl = m["templates"][m["instances"]["lo"]["template"]]
    assert tpl["copies"] == 2 and tpl["type"] == "add4"


def test_copias_do_macro_sao_identicas(flow):
    r = flow("hier_macros", *HIER, "--tb", data("tb_hier8.v"), "--macro", "fa", "--macro", "add4", "--fresh")
    p = r.placement()
    inst = p["macros"]["instances"]

    def rel(path):
        ox, oy = inst[path]["origin"]
        boxes = [f["box"] for f in p["footprints"] if f["module"] and
                 (f["module"] == path or f["module"].startswith(path + "."))]
        return sorted(tuple(round(v - o, 3) for v, o in zip(b, (ox, oy, ox, oy))) for b in boxes)
    assert rel("lo") and rel("lo") == rel("hi")


def test_editor_preve_onde_o_fluxo_poe_os_macros(tmp_path):
    fpf = tmp_path / "hier8.floorplan.json"
    fpf.write_text(json.dumps(FP_HIER), encoding="utf-8")
    r = run_flow(tmp_path / "out", *HIER, "--floorplan", fpf, "--place-only", "--fresh")
    assert r.rc == 0, r
    run = r.placement()
    pred = fpedit.check(FP_HIER, run, fpf.name)
    assert pred["errors"] == [], pred["errors"]
    real = run["macros"]["instances"]
    for m in pred["macros"]["instances"]:
        assert m["measured"], m
        assert m["origin"] == real[m["path"]]["origin"] and m["rect"] == real[m["path"]]["rect"], m["path"]
    assert real["hi"]["origin"] == [201.5, 11.5]                 # canto da fence + canal
    assert pred["board"] == run["board"]


def test_fence_pequena_para_o_macro(tmp_path):
    fpf = tmp_path / "fp.json"
    fpf.write_text(json.dumps({"macros": ["add4"], "modules": {"hi": {"type": "fence", "rect": [200, 10, 10, 10]}}}),
                   encoding="utf-8")
    r = run_flow(tmp_path / "out", *HIER, "--floorplan", fpf, "--place-only", "--fresh")
    assert r.rc == 3 and "não comporta o macro add4" in r.log, r


# -------------------------------------------------------- erros de entrada
def test_erros_de_entrada(tmp_path):
    r = run_flow(tmp_path / "a", *HIER[:-3], "--lib", lib_path("rtl") / "library.json")
    assert r.rc == 3 and "aponte para a pasta da família" in r.log, r
    fpf = tmp_path / "fp.json"
    fpf.write_text("{}", encoding="utf-8")
    r = run_flow(tmp_path / "b", *HIER, "--floorplan", fpf, "--flatten")
    assert r.rc == 3 and "--flatten" in r.log, r
    fpf.write_text('{"modules": {"x": {"type": "nada"}}}', encoding="utf-8")
    r = run_flow(tmp_path / "c", *HIER, "--floorplan", fpf)
    assert r.rc == 3 and "'type' deve ser" in r.log, r
    r = run_flow(tmp_path / "d", *HIER, "--macro", "naoexiste", "--place-only")
    assert r.rc == 3 and "naoexiste" in r.log, r


@pytest.mark.kicad
def test_drc_do_kicad(flow):
    from pcbflow import drc
    r = flow("c4_cmos", *COUNTER, "--lib", lib_path("cmos"), "--fresh")
    board = next(r.out.glob("*.kicad_pcb"))
    copy = r.out / "drc_copia.kicad_pcb"
    shutil.copy(board, copy)
    res = drc.run(drc.find_cli(), copy, r.out / "drc.json")
    assert drc.ok(res), drc.summary(res)


@pytest.mark.kicad
def test_drc_preenche_planos_pelo_pcbnew(flow, monkeypatch):
    """KiCad sem --refill-zones (8 e 9): a API pcbnew preenche os planos e salva a placa."""
    from pcbflow import drc
    cli = drc.find_cli()
    if not drc.kicad_python(cli):
        pytest.skip("Python do KiCad (pcbnew) não encontrado")
    r = flow("c4_cmos", *COUNTER, "--lib", lib_path("cmos"), "--fresh")
    copy = r.out / "drc_pcbnew.kicad_pcb"
    shutil.copy(next(r.out.glob("counter4_*.kicad_pcb")), copy)
    monkeypatch.setattr(drc, "drc_options", lambda cli: set())      # como no KiCad 9
    res = drc.run(cli, copy, r.out / "drc_pcbnew.json")
    assert res["fill"] == "pcbnew" and drc.ok(res), drc.summary(res)
    assert "filled_polygon" in copy.read_text(encoding="utf-8")


@pytest.mark.kicad
def test_drc_sem_como_preencher_planos(flow, monkeypatch):
    """Sem --refill-zones nem pcbnew: os planos ficam vazios e as desconexões
    das nets deles viram aviso, não erro."""
    from pcbflow import drc
    r = flow("c4_cmos", *COUNTER, "--lib", lib_path("cmos"), "--fresh")
    copy = r.out / "drc_vazio.kicad_pcb"
    shutil.copy(next(r.out.glob("counter4_*.kicad_pcb")), copy)
    monkeypatch.setattr(drc, "drc_options", lambda cli: set())
    monkeypatch.setattr(drc, "kicad_python", lambda cli: None)
    res = drc.run(drc.find_cli(), copy, r.out / "drc_vazio.json")
    assert res["fill"] is None and drc.ok(res), drc.summary(res)
    assert res["warnings"]["plano sem preencher"] > 0
    assert any("planos não preenchidos" in line for line in drc.summary(res))


# --------------------------------------------------------------- conectores
FP_CONN = {"connectors": [
    {"name": "J_A", "side": "left", "at": 30, "pins": ["VDD", "GND", "a[*]", "GND"]},
    {"name": "J_B", "side": "top", "pins": ["b[7:0]", "GND", "VDD"]},
    {"name": "J_S", "side": "right", "at": 40, "pins": ["s[*]", "GND"]},
    {"name": "J_CTL", "side": "bottom", "at": 40, "pins": ["ci", "co", "NC", "GND", "VDD"]}]}


def _conn_run(flow, tmp_path_factory, name, *args):
    fpf = tmp_path_factory.mktemp("fp") / "hier8.floorplan.json"
    fpf.write_text(json.dumps(FP_CONN), encoding="utf-8")
    return flow(name, *HIER[:-1], "--tb", data("tb_hier8.v"), "--floorplan", fpf, "--fresh", *args)


@pytest.mark.parametrize("lib, layers", [("cmos", "4"), ("rtl", "2")])
def test_conectores_nas_quatro_bordas(flow, tmp_path_factory, lib, layers):
    r = _conn_run(flow, tmp_path_factory, f"conn_{lib}_{layers}", "--lib", lib_path(lib), "--layers", layers,
                  "--no-drc")
    routed_ok(r)
    sims_ok(r)
    p = r.placement()
    conns = {c["name"]: c for c in p["connectors"]}
    assert set(conns) == {"J_A", "J_B", "J_S", "J_CTL"}            # nenhuma porta sobrou para os automáticos
    assert conns["J_A"]["at"] == 30 and conns["J_S"]["at"] == 40 and conns["J_CTL"]["at"] == 40
    assert conns["J_CTL"]["pins"] == ["ci", "co", "NC", "GND", "VDD"]
    pcb = next(r.out.glob("*.kicad_pcb")).read_text(encoding="utf-8")
    # em cima e embaixo, a barra da biblioteca girada 90°; os pinos com o nome da porta
    for ref, value in (("J2", "J_B"), ("J4", "J_CTL")):
        block = pcb.split(f'"Reference" "{ref}"')[0].rsplit("(footprint", 1)[1]
        assert re.search(r"\(at [\d.]+ [\d.]+ 90\)", block), ref
    assert '(pinfunction "b[7]")' in pcb and '(pinfunction "NC")' in pcb
    W, H = p["board"]
    x_ctl = 40 + 4 * 2.54                                           # último pino do J_CTL
    assert W > x_ctl and H > 30 + 10 * 2.54                         # a placa contém os conectores


@pytest.mark.kicad
def test_conectores_drc(flow, tmp_path_factory):
    from pcbflow import drc
    r = _conn_run(flow, tmp_path_factory, "conn_cmos_4", "--lib", lib_path("cmos"), "--layers", "4", "--no-drc")
    copy = r.out / "drc_conn.kicad_pcb"
    shutil.copy(next(r.out.glob("hier8_*.kicad_pcb")), copy)
    res = drc.run(drc.find_cli(), copy, r.out / "drc_conn.json")
    assert drc.ok(res), drc.summary(res)


def test_conectores_com_macros(tmp_path):
    fpf = tmp_path / "fp.json"
    fpf.write_text(json.dumps(dict(FP_CONN, macros=["add4"])), encoding="utf-8")
    r = run_flow(tmp_path / "out", *HIER, "--floorplan", fpf, "--fresh")
    routed_ok(r)
    assert {c["name"] for c in r.placement()["connectors"]} == {"J_A", "J_B", "J_S", "J_CTL"}


@pytest.mark.parametrize("conns, msg", [
    ([{"name": "J", "side": "left", "pins": ["zz"]}], "'zz' não é uma porta do topo"),
    ([{"name": "J", "side": "left", "pins": ["ci"]}, {"name": "K", "side": "top", "pins": ["ci"]}],
     "já está no conector"),
    ([{"name": "J", "side": "left", "at": 6, "pins": ["a[*]"]}, {"name": "K", "side": "top", "at": 6, "pins": ["ci"]}],
     "se sobrepõem"),
])
def test_conectores_invalidos(tmp_path, conns, msg):
    fpf = tmp_path / "fp.json"
    fpf.write_text(json.dumps({"connectors": conns}), encoding="utf-8")
    r = run_flow(tmp_path / "out", *HIER, "--floorplan", fpf, "--place-only", "--fresh")
    assert r.rc == 3 and msg in r.log, r


def test_conector_fora_da_placa_fixa(tmp_path):
    fpf = tmp_path / "fp.json"
    fpf.write_text(json.dumps({"board": {"width": 300, "height": 300},
                               "connectors": [{"name": "J", "side": "bottom", "at": 290, "pins": ["s[*]"]}]}),
                   encoding="utf-8")
    r = run_flow(tmp_path / "out", *HIER, "--floorplan", fpf, "--place-only", "--fresh")
    assert r.rc == 3 and "sai da placa" in r.log, r
