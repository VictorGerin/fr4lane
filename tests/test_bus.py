"""Barramentos tri-state: driver de coletor aberto (TBUF) e pull-up (PULLUP) da
família RTL, o check do Yosys com vários drivers, a troca de $_TBUF_ pelo
driver da família, os pull-ups por linha e o fluxo completo num barramento.
Pilha de placas: porta inout, placa sem pull-ups, buffers nas portas e o
pcbflow-system (drive entre placas e simulação do sistema)."""

import os
import re
import subprocess
import sys

import pytest

from conftest import PCBFLOW, data, lib_path, run_flow
from pcbflow import buffering, drive, floorplan, synth
from pcbflow.library import Library
from pcbflow.netlist import Design, Port, add_pullups, elaborate, write_switch_level_verilog

BUS = ["--top", "bus4", "--src", data("bus4.v"), "--tb", data("tb_bus4.v")]


@pytest.fixture(scope="module")
def rtl():
    return Library(lib_path("rtl"))


def test_familias_com_e_sem_barramento(rtl):
    assert rtl.tristate == {"cell": "TBUF", "data": "A", "enable": "E", "out": "Y"}
    assert rtl.pullup == ("PULLUP", "Y")
    # o Yosys não escolhe nenhuma das duas: o pcbflow as põe depois da síntese
    assert not rtl.usable("TBUF") and not rtl.usable("PULLUP")
    for family in ("cmos", "relay"):
        lib = Library(lib_path(family))
        assert lib.tristate is None and lib.pullup is None


def test_driver_puxa_a_corrente_do_pullup(rtl):
    el, drives = drive.library_drive(rtl)
    tb = drives["TBUF"]
    # o enable alimenta a base de um NPN que afunda a corrente do pull-up da linha
    assert tb.pins["E"].loads[0].ic == pytest.approx(drives["PULLUP"].pins["Y"].g_up
                                                     * (el.vdd_max - 2 * el.vce_sat) / (1 - el.tol))
    assert tb.pins["Y"].g_up == 0                 # coletor aberto: não leva a linha a 1
    assert drive.check_internal(rtl, el, drives) == []


def test_check_aceita_so_barramento():
    tbuf = ("Warning: multiple conflicting drivers for top.\\bus [3]:\n"
            "    port Y[0] of cell $flatten\\u_a.$auto$x$1 ($_TBUF_)\n"
            "    port Y[0] of cell $flatten\\u_b.$auto$x$2 ($_TBUF_)\n")
    mixed = ("Warning: multiple conflicting drivers for top.\\y:\n"
             "    port Y[0] of cell g1 ($_TBUF_)\n"
             "    port Y of cell g2 (NAND2)\n")
    other = "Warning: wire top.\\q is used but has no driver.\n"
    assert synth.check_problems(tbuf) == []
    assert len(synth.check_problems(tbuf + mixed + other)) == 2


def _design(rtl, cells):
    d = Design("t", [], [], rtl.vdd, rtl.gnd)
    for inst, (cell, yname, conns, mod) in cells.items():
        d.instances[inst] = (cell, yname)
        d.conns[inst] = conns
        d.inst_module[inst] = mod
    return d


def test_um_pullup_por_linha(rtl):
    d = _design(rtl, {
        "U1": ("TBUF", "u0.a.$t1", {"A": "x", "E": "e1", "Y": "bus"}, "u0.a"),
        "U2": ("TBUF", "u0.b.$t2", {"A": "y", "E": "e2", "Y": "bus"}, "u0.b"),
        "U3": ("NAND2", "u0.$g", {"A": "bus", "B": "e1", "Y": "z"}, "u0"),
    })
    add_pullups(rtl, d)
    pu = [i for i, (c, _) in d.instances.items() if c == "PULLUP"]
    assert len(pu) == 1
    # no módulo que contém os dois drivers, com nome tirado do primeiro (igual nas cópias de um macro)
    assert d.inst_module[pu[0]] == "u0" and d.instances[pu[0]][1] == "u0.$pullup$a/$t1"
    assert d.conns[pu[0]] == {"Y": "bus"}


def test_driver_comum_nao_divide_net(rtl):
    d = _design(rtl, {
        "U1": ("TBUF", "$t1", {"A": "x", "E": "e1", "Y": "bus"}, ""),
        "U2": ("NAND2", "$g", {"A": "x", "B": "e1", "Y": "bus"}, ""),
    })
    with pytest.raises(ValueError, match="só drivers de barramento"):
        add_pullups(rtl, d)


def test_netlist_de_componentes_liga_drivers_e_pullup(rtl, tmp_path):
    d = _design(rtl, {
        "U1": ("TBUF", "$t1", {"A": "x", "E": "e1", "Y": "bus"}, ""),
        "U2": ("TBUF", "$t2", {"A": "y", "E": "e2", "Y": "bus"}, ""),
    })
    add_pullups(rtl, d)
    elaborate(rtl, d)
    f = tmp_path / "sw.v"
    write_switch_level_verilog(rtl, d, f)
    text = f.read_text()
    # um só nó $raw e um só atraso para a linha, com os dois drivers e o pull-up nele
    assert text.count("reg \\n:bus$d ") == 1
    assert text.count("\\n:bus$raw ") >= 4


@pytest.mark.tools
def test_familia_sem_driver_recusa_tri_state(tmp_path):
    r = run_flow(tmp_path / "out", *BUS, "--lib", lib_path("cmos"), "--synth-only")
    assert r.rc == 3, r
    assert "não tem driver de barramento" in r.log


@pytest.mark.tools
def test_barramento_simulado(tmp_path):
    r = run_flow(tmp_path / "out", *BUS, "--lib", lib_path("rtl"), "--synth-only")
    assert r.rc == 0, r
    assert re.search(r"barramentos: 4 linha\(s\) com 12 drivers de coletor aberto", r.log), r
    assert re.search(r"gate-level:\s+OK", r.log) and re.search(r"componentes:\s+OK", r.log), r


@pytest.mark.slow
def test_barramento_placa_completa(tmp_path):
    r = run_flow(tmp_path / "out", *BUS, "--lib", lib_path("rtl"), "--no-drc")
    assert r.rc == 0, r
    assert re.search(r"violações de folga: 0\b", r.log) and re.search(r"nets incompletas: 0\b", r.log), r
    rep = r.file("report.md").read_text(encoding="utf-8")
    assert "| PULLUP | 4 |" in rep and "| TBUF | 12 |" in rep


# ------------------------------------------------------------ pilha de placas
def test_floorplan_da_placa_da_pilha():
    fp = floorplan.parse({"bus_pullups": False, "buffer_ports": True})
    assert fp.bus_pullups is False and fp.buffer_ports is True
    fp = floorplan.parse({})
    assert fp.bus_pullups is True and fp.buffer_ports is False
    with pytest.raises(floorplan.FloorplanError, match="bus_pullups"):
        floorplan.parse({"bus_pullups": "não"})


def test_porta_inout_liga_nos_dois_sentidos(rtl, tmp_path):
    d = _design(rtl, {
        "U1": ("TBUF", "$t1", {"A": "x", "E": "e1", "Y": "bus"}, ""),
        "U2": ("NAND2", "$g", {"A": "bus", "B": "e1", "Y": "y"}, ""),
    })
    d.ports = [Port("bus", "inout", "bus"), Port("x", "input", "x"), Port("e1", "input", "e1"),
               Port("y", "output", "y")]
    add_pullups(rtl, d, pullups=False)
    assert "PULLUP" not in {c for c, _ in d.instances.values()}
    elaborate(rtl, d)
    f = tmp_path / "sw.v"
    write_switch_level_verilog(rtl, d, f)
    text = f.read_text()
    # tran entre a porta e a linha; o driver liga direto nela (sem o atraso de saída)
    assert "tran \\n:$io.bus (bus, \\n:bus );" in text
    assert "\n:bus$raw" not in text


def test_buffer_nas_portas(rtl):
    d = _design(rtl, {
        "U1": ("TBUF", "$t1", {"A": "x", "E": "e1", "Y": "bus"}, ""),
        "U2": ("NAND2", "$g", {"A": "bus", "B": "e1", "Y": "y"}, ""),
        "U3": ("INV", "$i", {"A": "bus", "Y": "z"}, ""),
    })
    d.ports = [Port("bus", "inout", "bus"), Port("x", "input", "x"), Port("e1", "input", "e1"),
               Port("y", "output", "y"), Port("z", "output", "z")]
    el, drives = drive.library_drive(rtl)
    done = dict(buffering.buffer_ports(rtl, d, el, drives))
    assert done == {"bus": 2, "x": 1, "e1": 2}
    bufs = {d.conns[i]["A"]: d.conns[i]["Y"] for i, (c, _) in d.instances.items() if c == "BUF"}
    # as cargas da linha passam para trás do buffer; o driver do barramento fica nela
    assert d.conns["U2"]["A"] == d.conns["U3"]["A"] == bufs["bus"]
    assert d.conns["U1"]["Y"] == "bus" and d.conns["U1"]["A"] == bufs["x"]


def _stack_project(tmp_path):
    for f in ("stack_boards.v", "stack.v", "tb_stack.v"):
        (tmp_path / f).write_text(data(f).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "pcbflow.json").write_text(
        '{"src": ["stack_boards.v", "stack.v"], "tb": "tb_{top}.v", "out": "build"}', encoding="utf-8")
    return tmp_path


def _run_system(cwd, *args):
    env = dict(os.environ, PYTHONPATH=str(PCBFLOW), PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "pcbflow.system", *args], cwd=cwd, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    return r.returncode, r.stdout + r.stderr


SYSTEM = ["--top", "stack", "--boards", "ctl", "card", "--lib", "rtl"]


@pytest.mark.tools
def test_sistema_de_placas(tmp_path):
    proj = _stack_project(tmp_path)
    rc, log = _run_system(proj, *SYSTEM)
    assert rc == 3 and "falta a rodada da placa ctl" in log, log
    assert run_flow(None, "--top", "ctl", "--lib", "rtl", "--synth-only", cwd=proj).rc == 0
    r = run_flow(None, "--top", "card", "--lib", "rtl", "--synth-only", "--no-bus-pullups", cwd=proj)
    assert r.rc == 0 and "sem pull-ups nesta placa" in r.log, r
    rc, log = _run_system(proj, *SYSTEM)
    assert rc == 0, log
    assert "placas montadas: card ×2, ctl" in log
    assert "com problema: 0" in log
    assert re.search(r"gate-level:\s+OK", log) and re.search(r"componentes:\s+OK", log), log
    assert (proj / "build" / "stack_rtl_sistema" / "report.md").is_file()
    # com pull-ups também nos cartões, cada linha teria três: o sistema acusa
    assert run_flow(None, "--top", "card", "--lib", "rtl", "--synth-only", cwd=proj).rc == 0
    rc, log = _run_system(proj, *SYSTEM)
    assert rc == 1 and "pull-ups em 3 placas" in log, log
