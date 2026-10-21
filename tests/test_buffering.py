"""Buffers por fan-out: árvores balanceadas, entradas do topo, função
preservada (simulação de componentes) e macros com o mesmo molde."""

import re

import pytest

from conftest import FAMILIES, data, lib_path, run_flow
from fr4lane import buffering
from fr4lane.netlist import common_module

FAN = ["--top", "fan40", "--src", data("fan40.v"), "--tb", data("tb_fan40.v"), "--synth-only"]


def test_lca():
    assert common_module(["u0.a", "u0.b.c"]) == "u0"
    assert common_module(["u0", "u1"]) == ""
    assert common_module(["", "u0"]) == ""
    assert common_module(["u0.a"]) == "u0.a"


@pytest.mark.slow
@pytest.mark.parametrize("family", FAMILIES)
def test_buffers_resolvem_o_fanout(tmp_path, family):
    r = run_flow(tmp_path, *FAN, "--lib", lib_path(family))
    assert r.rc == 0, r
    assert re.search(r"buffers: \d+ BUF em \d+ nets", r.log), r
    assert "AVISO" not in r.log, r                                   # nada acima do limite depois deles
    # a simulação de componentes já tem os buffers: a função continua a mesma
    assert re.search(r"gate-level:\s+OK", r.log) and re.search(r"componentes:\s+OK", r.log), r


@pytest.mark.slow
def test_sem_buffer_so_avisa(tmp_path):
    r = run_flow(tmp_path, *FAN, "--lib", lib_path("cmos"), "--no-buffer")
    assert r.rc == 0 and "buffers:" not in r.log, r
    assert re.search(r"AVISO: \d+ nets com fan-out", r.log) and "(entrada clk)" in r.log, r


@pytest.mark.slow
def test_arvore_balanceada_no_relatorio(tmp_path):
    r = run_flow(tmp_path, "--top", "fan2", "--src", data("fan2.v"), data("fan40.v"), "--lib", lib_path("cmos"),
                 "--place-only")
    assert r.rc == 0, r
    assert "árvores de até 2 níveis" in r.log, r                     # 80 cargas no clock: dois níveis


@pytest.mark.tools
def test_copias_de_macro_ganham_os_mesmos_buffers(tmp_path):
    """Com buffers dentro de cada instância, as duas continuam com a mesma
    estrutura (o mesmo molde de macro)."""
    from fr4lane import drive, hier, netlist, synth
    from fr4lane.library import Library
    lib = Library("cmos")
    lib.write_liberty(tmp_path / "cells.lib")
    j, _, _, hj = synth.run_yosys([data("fan2.v"), data("fan40.v")], "fan2", tmp_path / "cells.lib", tmp_path,
                                  latches=lib.latch_techmap())
    design = netlist.load_yosys_json(j, "fan2", lib, hj)
    el, drives = drive.library_drive(lib)
    res = buffering.buffer_design(lib, design, el, drives)
    inner = [t for t in res.trees if t[0].startswith(("u0.", "u1."))]
    assert inner and len([t for t in inner if t[0].startswith("u0.")]) == len(inner) // 2
    _, _, rep = hier.analyze(design, ["fan40"])
    assert rep["u0"] == rep["u1"]
    for inst, (cell, _) in design.instances.items():
        if inst.startswith("B"):
            assert cell == res.cell
