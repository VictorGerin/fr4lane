"""Simulação analógica das células (pcbflow-cellsim): modelos e cantos do
library.json, netlist do ngspice gerado a partir dos .sp, e, com o ngspice, as
células da família RTL e montagens sabotadas de propósito (têm de falhar)."""

import shutil

import pytest

from conftest import LIB, lib_path
from pcbflow import cellsim
from pcbflow.library import Library, LibraryError


@pytest.fixture(scope="module")
def rtl():
    return Library(lib_path("rtl"))


def test_modelos_e_cantos_da_familia(rtl):
    models, corners = cellsim.spice_setup(rtl)
    kind, params = models["NPN"]
    assert kind == "NPN" and params["Bf"] == "250" and params["Tr"] == "10n"
    names = [c.name for c in corners]
    assert names[0] == "típico" and {"lento", "rápido", "quente"} <= set(names)
    lento = next(c for c in corners if c.name == "lento")
    assert lento.params["NPN"]["Bf"] == 110 and lento.vdd == 4.75


def test_familia_sem_spice():
    with pytest.raises(cellsim.CellSimError, match="não declara \"spice\""):
        cellsim.spice_setup(Library(lib_path("cmos")))


def test_netlist_das_celulas(rtl):
    text = cellsim.subckt_text(rtl, ["DFFR"])
    # os subcircuitos usados vêm antes, e os resistores ganham a escala do canto
    assert text.index(".subckt INV") < text.index(".subckt DFFR")
    assert "RL VDD Y {1000*kup}" in text and "R1 A b1 {10000*kb}" in text
    assert "X9 R rn VDD GND INV" in text


def _copy(tmp_path, cell, old, new):
    dst = tmp_path / "lib" / "rtl"
    shutil.copytree(lib_path("rtl"), dst)
    shutil.copy(LIB / "footprints.json", tmp_path / "lib")
    f = dst / "cells" / cell / f"{cell}.sp"
    text = f.read_text(encoding="utf-8")
    assert old in text
    f.write_text(text.replace(old, new), encoding="utf-8")
    return dst


def test_nos_que_so_diferem_na_caixa(tmp_path):
    # para o SPICE, R e r são o mesmo nó: o DFFR antigo ligava a entrada do inversor na saída
    with pytest.raises(LibraryError, match="só diferem na caixa"):
        Library(_copy(tmp_path, "DFFR", "X9 R  rn", "X9 R  r "))


@pytest.mark.spice
def test_celulas_rtl_no_ngspice(rtl, tmp_path):
    res, corners, warns = cellsim.check_family(rtl, ["INV", "NOR2", "TBUF", "DFF"], tmp_path, log=lambda m: None)
    for cell, by in res.items():
        for corner, r in by.items():
            assert r["ok"], (cell, corner, r["fails"])
    dff = res["DFF"]["típico"]
    assert 2e-7 < dff["ckq"][0] < 2e-6 and dff["period"] and dff["hold"][0]
    assert not [w for w in warns if "capturaria" in w]          # hold < clock -> Q mínimo


@pytest.mark.spice
@pytest.mark.parametrize("cell, old, new", [
    ("NOR2", "Q2 Y   b2 GND NPN", "Q2 b2  Y  GND NPN"),           # coletor e base trocados
    ("DFF", "X6 Q  n3 QN", "X6 Q  n2 QN"),                       # latch de saída ligado no nó errado
])
def test_montagem_errada_falha(tmp_path, cell, old, new):
    lib = Library(_copy(tmp_path, cell, old, new))
    res, *_ = cellsim.check_family(lib, [cell], tmp_path / "out", log=lambda m: None)
    assert not res[cell]["típico"]["ok"]


@pytest.mark.spice
def test_exportacao(rtl, tmp_path):
    res, corners, warns = cellsim.check_family(rtl, ["INV"], tmp_path / "run", log=lambda m: None)
    cellsim.export(rtl, ["INV"], tmp_path / "pub", res, corners, warns, log=lambda m: None)
    cir = (tmp_path / "pub" / "INV.cir").read_text(encoding="utf-8")
    assert "* vetores de teste" in cir and ".model NPN NPN(" in cir and "wrdata INV.dat" in cir
    assert (tmp_path / "pub" / "INV.png").stat().st_size > 5000
    assert "![INV](INV.png)" in (tmp_path / "pub" / "README.md").read_text(encoding="utf-8")
