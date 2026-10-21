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
    m = models["NPN"]
    assert m.kind == "NPN" and m.params["Bf"] == "250" and m.params["Tr"] == "10n"
    names = [c.name for c in corners]
    assert names[0] == "típico" and {"lento", "rápido", "quente"} <= set(names)
    lento = next(c for c in corners if c.name == "lento")
    assert lento.params["NPN"]["Bf"] == 110 and lento.vdd == 4.75


def test_familia_sem_spice(tmp_path):
    import json
    dst = tmp_path / "lib" / "cmos"
    shutil.copytree(lib_path("cmos"), dst)
    shutil.copy(LIB / "footprints.json", tmp_path / "lib")
    meta = json.loads((dst / "library.json").read_text(encoding="utf-8"))
    del meta["spice"]
    (dst / "library.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(cellsim.CellSimError, match="não declara \"spice\""):
        cellsim.spice_setup(Library(dst))


@pytest.mark.parametrize("family, keys", [
    ("cmos", {"NMOS", "PMOS"}),
    ("dtl", {"NPN", "DIODE"}),
    ("ctl", {"CORE", "NPN"}),
    ("cdl", {"CORE", "DIODE"}),
    ("relay", {"RELAY", "DIODE"}),
])
def test_modelos_das_outras_familias(family, keys):
    models, corners = cellsim.spice_setup(Library(lib_path(family)))
    assert set(models) == keys
    if family == "relay":
        assert models["RELAY"].kind == "SUBCKT" and models["RELAY"].subckt == "G5V1"
        assert {c.name for c in corners} == {"típico", "lento", "quente", "rápido"}
    elif family == "dtl":
        assert models["NPN"].kind == "NPN" and models["DIODE"].kind == "D"
        assert {c.name for c in corners} == {"típico", "lento", "quente", "rápido"}
    elif family == "ctl":
        assert models["CORE"].kind == "SUBCKT" and models["CORE"].subckt == "FCORE"
        assert {c.name for c in corners} == {"típico", "lento", "quente", "rápido"}
    elif family == "cdl":
        assert models["CORE"].kind == "SUBCKT" and models["CORE"].subckt == "MCORE"
        assert {c.name for c in corners} == {"típico", "lento", "quente", "rápido"}
    else:
        assert models["NMOS"].instance == "L=100u W=100u"
        assert corners[0].step == 2e-6 and corners[0].levels["vih"] == 0.9


@pytest.mark.spice
def test_somador_no_ngspice(tmp_path):
    from conftest import PCBFLOW
    lib = Library(lib_path("cmos"))
    res, design = cellsim.check_design(lib, [PCBFLOW / "examples/demo/demo_top.v"], "add4", tmp_path,
                                       vectors=40, log=lambda m: None)
    assert all(r["ok"] for r in res.values()), {k: r["fails"][:3] for k, r in res.items()}
    assert res["típico"]["tpd"] and res["típico"]["vectors"] == 40


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
