"""Barramentos tri-state: driver (TBUF, driver_type open_drain) e terminação
(PULLUP, driver_type pull_up) da família RTL, o check do Yosys com vários
drivers, a troca de $_TBUF_ pelo driver da família, a terminação por linha e o
fluxo completo num barramento. Pilha de placas: porta inout, terminação só em
algumas linhas, buffers nas portas e o fr4lane-system (drive entre placas e
simulação do sistema)."""

import os
import re
import shutil
import subprocess
import sys

import pytest

from conftest import LIB, FR4LANE, data, lib_path, run_flow
from fr4lane import buffering, drive, floorplan, synth
from fr4lane.library import Library, LibraryError
from fr4lane.netlist import Design, Port, add_termination, elaborate, write_switch_level_verilog

BUS = ["--top", "bus4", "--src", data("bus4.v"), "--tb", data("tb_bus4.v")]


@pytest.fixture(scope="module")
def rtl():
    return Library(lib_path("rtl"))


def test_familias_com_e_sem_barramento(rtl):
    assert rtl.tristate == {"cell": "TBUF", "data": "A", "enable": "E", "out": "Y", "drives": 0}
    assert rtl.terminator == {"cell": "PULLUP", "pin": "Y", "level": 1}
    # o Yosys não escolhe nenhuma das duas: o fr4lane as põe depois da síntese
    assert not rtl.usable("TBUF") and not rtl.usable("PULLUP")
    for family in ("cmos", "relay"):
        lib = Library(lib_path(family))
        assert lib.tristate is None and lib.terminator is None


def test_driver_puxa_a_corrente_da_terminacao(rtl):
    el, drives = drive.library_drive(rtl)
    tb = drives["TBUF"]
    # o enable alimenta a base de um NPN que afunda a corrente da terminação (pull-up) da linha
    assert tb.pins["E"].loads[0].ic == pytest.approx(drives["PULLUP"].pins["Y"].g_up
                                                     * (el.vdd_max - 2 * el.vce_sat) / (1 - el.tol))
    assert tb.pins["Y"].g_up == 0                 # open_drain: não leva a linha a 1
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


def test_uma_terminacao_por_linha(rtl):
    d = _design(rtl, {
        "U1": ("TBUF", "u0.a.$t1", {"A": "x", "E": "e1", "Y": "bus"}, "u0.a"),
        "U2": ("TBUF", "u0.b.$t2", {"A": "y", "E": "e2", "Y": "bus"}, "u0.b"),
        "U3": ("NAND2", "u0.$g", {"A": "bus", "B": "e1", "Y": "z"}, "u0"),
    })
    add_termination(rtl, d)
    pu = [i for i, (c, _) in d.instances.items() if c == "PULLUP"]
    assert len(pu) == 1
    # no módulo que contém os dois drivers, com nome tirado do primeiro (igual nas cópias de um macro)
    assert d.inst_module[pu[0]] == "u0" and d.instances[pu[0]][1] == "u0.$busterm$a/$t1"
    assert d.conns[pu[0]] == {"Y": "bus"}


def test_driver_comum_nao_divide_net(rtl):
    d = _design(rtl, {
        "U1": ("TBUF", "$t1", {"A": "x", "E": "e1", "Y": "bus"}, ""),
        "U2": ("NAND2", "$g", {"A": "x", "B": "e1", "Y": "bus"}, ""),
    })
    with pytest.raises(ValueError, match="só drivers de barramento"):
        add_termination(rtl, d)


def test_netlist_de_componentes_liga_drivers_e_terminacao(rtl, tmp_path):
    d = _design(rtl, {
        "U1": ("TBUF", "$t1", {"A": "x", "E": "e1", "Y": "bus"}, ""),
        "U2": ("TBUF", "$t2", {"A": "y", "E": "e2", "Y": "bus"}, ""),
    })
    add_termination(rtl, d)
    elaborate(rtl, d)
    f = tmp_path / "sw.v"
    write_switch_level_verilog(rtl, d, f)
    text = f.read_text()
    # um só nó $raw e um só atraso para a linha, com os dois drivers e a terminação nele
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
    assert "barramentos: 12 drivers (TBUF), terminação (PULLUP) em 4 linha(s)" in r.log, r
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
    fp = floorplan.parse({"bus_termination": False, "buffer_ports": True})
    assert fp.bus_termination is False and fp.buffer_ports is True
    fp = floorplan.parse({})
    assert fp.bus_termination is True and fp.buffer_ports is False
    fp = floorplan.parse({"bus_termination": ["bus_a", "ack"], "buffer_ports": ["d[3:0]"]})
    assert fp.bus_termination == ["bus_a", "ack"] and fp.buffer_ports == ["d[3:0]"]
    for bad in ("não", [], ["ok", ""], [3]):
        with pytest.raises(floorplan.FloorplanError, match="bus_termination"):
            floorplan.parse({"bus_termination": bad})


def test_porta_inout_liga_nos_dois_sentidos(rtl, tmp_path):
    d = _design(rtl, {
        "U1": ("TBUF", "$t1", {"A": "x", "E": "e1", "Y": "bus"}, ""),
        "U2": ("NAND2", "$g", {"A": "bus", "B": "e1", "Y": "y"}, ""),
    })
    d.ports = [Port("bus", "inout", "bus"), Port("x", "input", "x"), Port("e1", "input", "e1"),
               Port("y", "output", "y")]
    add_termination(rtl, d, termination=False)
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
    (tmp_path / "fr4lane.json").write_text(
        '{"src": ["stack_boards.v", "stack.v"], "tb": "tb_{top}.v", "out": "build"}', encoding="utf-8")
    return tmp_path


def _run_system(cwd, *args):
    env = dict(os.environ, PYTHONPATH=str(FR4LANE), PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "fr4lane.system", *args], cwd=cwd, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    return r.returncode, r.stdout + r.stderr


SYSTEM = ["--top", "stack", "--boards", "ctl", "card", "--lib", "rtl"]


@pytest.mark.tools
def test_sistema_de_placas(tmp_path):
    proj = _stack_project(tmp_path)
    rc, log = _run_system(proj, *SYSTEM)
    assert rc == 3 and "falta a rodada da placa ctl" in log, log
    assert run_flow(None, "--top", "ctl", "--lib", "rtl", "--synth-only", cwd=proj).rc == 0
    r = run_flow(None, "--top", "card", "--lib", "rtl", "--synth-only", "--no-bus-termination", cwd=proj)
    assert r.rc == 0 and "sem terminação nesta placa" in r.log, r
    rc, log = _run_system(proj, *SYSTEM)
    assert rc == 0, log
    assert "placas montadas: card ×2, ctl" in log
    assert "com problema: 0" in log
    assert re.search(r"gate-level:\s+OK", log) and re.search(r"componentes:\s+OK", log), log
    assert (proj / "build" / "stack_rtl_sistema" / "report.md").is_file()
    # com terminação também nos cartões, cada linha teria três: o sistema acusa
    assert run_flow(None, "--top", "card", "--lib", "rtl", "--synth-only", cwd=proj).rc == 0
    rc, log = _run_system(proj, *SYSTEM)
    assert rc == 1 and "terminação em 3 placas" in log, log


def _two_buses(rtl):
    """Placa com dois barramentos que saem dela (bus_a e bus_b, 2 bits cada)."""
    d = _design(rtl, {
        f"U{k}": ("TBUF", f"$t{k}", {"A": "x", "E": "e", "Y": net}, "")
        for k, net in enumerate(("a0", "a1", "b0", "b1"), 1)
    })
    d.ports = [Port("bus_a[0]", "inout", "a0"), Port("bus_a[1]", "inout", "a1"),
               Port("bus_b[0]", "inout", "b0"), Port("bus_b[1]", "inout", "b1"),
               Port("x", "input", "x"), Port("e", "input", "e")]
    return d


def _terminated(d):
    return sorted(d.conns[i]["Y"] for i, (c, _) in d.instances.items() if c == "PULLUP")


def test_terminacao_so_em_algumas_portas(rtl):
    # dois barramentos independentes: a terminação de cada um pode ficar numa placa
    for which, want in ((True, ["a0", "a1", "b0", "b1"]), (False, []), (["bus_a"], ["a0", "a1"]),
                        (["bus_b[1]"], ["b1"]), (["bus_a[0]", "bus_b"], ["a0", "b0", "b1"])):
        d = _two_buses(rtl)
        add_termination(rtl, d, termination=which)
        assert _terminated(d) == want, which


def test_terminacao_em_porta_que_nao_e_barramento(rtl):
    with pytest.raises(ValueError, match="'x' não é uma linha de barramento"):
        add_termination(rtl, _two_buses(rtl), termination=["x"])
    with pytest.raises(floorplan.FloorplanError, match="não é uma porta"):
        add_termination(rtl, _two_buses(rtl), termination=["bus_c"])


def test_buffer_so_em_algumas_portas(rtl):
    d = _design(rtl, {
        "U1": ("NAND2", "$g", {"A": "a", "B": "b", "Y": "y"}, ""),
        "U2": ("INV", "$i", {"A": "a", "Y": "z"}, ""),
    })
    d.ports = [Port("a", "input", "a"), Port("b", "input", "b"), Port("y", "output", "y"), Port("z", "output", "z")]
    el, drives = drive.library_drive(rtl)
    assert buffering.buffer_ports(rtl, d, el, drives, ["a"]) == [("a", 2)]
    assert d.conns["U1"]["B"] == "b"                 # b ficou sem buffer
    with pytest.raises(ValueError, match="é uma saída"):
        buffering.buffer_ports(rtl, d, el, drives, ["y"])


def _rtl_copy(tmp_path, cell, old, new):
    dst = tmp_path / "lib" / "rtl"
    shutil.copytree(lib_path("rtl"), dst)
    shutil.copy(LIB / "footprints.json", tmp_path / "lib")
    f = dst / "cells" / cell / f"{cell}.lib"
    text = f.read_text(encoding="utf-8")
    assert old in text
    f.write_text(text.replace(old, new), encoding="utf-8")
    return dst


@pytest.mark.parametrize("cell, old, new, msg", [
    ("TBUF", "driver_type : open_drain; ", "", "declare driver_type : open_drain"),
    ("PULLUP", "driver_type : pull_up;", "driver_type : pull_down;", "function"),
    ("PULLUP", 'function : "1"; driver_type : pull_up;', 'function : "0"; driver_type : pull_down;',
     "a terminação deve segurar o nível que o driver"),
])
def test_papeis_de_barramento_pelo_liberty(tmp_path, cell, old, new, msg):
    with pytest.raises(LibraryError, match=msg):
        Library(_rtl_copy(tmp_path, cell, old, new))
