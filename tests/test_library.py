"""Famílias de células: leitura, consistência .sp x .lib x parts/footprints, drive
em pior caso e, com o Icarus, a simulação de cada montagem contra o Liberty."""

import shutil

import pytest

from conftest import FAMILIES, LIB, lib_path
from fr4lane import cellcheck, drive, liberty, spice
from fr4lane.library import Library, LibraryError


def test_ha_familias():
    assert {"cmos", "rtl", "relay"} <= set(FAMILIES)


@pytest.mark.parametrize("family", FAMILIES)
def test_familia_consistente(family):
    lib = Library(lib_path(family))
    assert lib.cells, "família sem células"
    assert lib.check() == []
    # toda célula tem montagem com os mesmos pinos lógicos do .lib (mais alimentação)
    for name, cell in lib.cells.items():
        assert set(cell.pins) <= set(lib.subckts[name].pins), name


@pytest.mark.parametrize("family", FAMILIES)
def test_drive_pior_caso(family):
    lib = Library(lib_path(family))
    el, drives = drive.library_drive(lib)
    if el is None:
        pytest.skip("família sem modelo DC")
    assert drive.check_internal(lib, el, drives) == []


@pytest.mark.parametrize("family", FAMILIES)
def test_latch_em_todas_as_familias(family):
    lib = Library(lib_path(family))
    assert "DLAT" in lib.cells and lib.cells["DLAT"].latch
    types, text = lib.latch_techmap()
    assert "$_DLATCH_P_" in types
    assert "DLAT _TECHMAP_REPLACE_" in text


@pytest.mark.parametrize("family", FAMILIES)
def test_liberty_gerado_reler(family, tmp_path):
    lib = Library(lib_path(family))
    out = tmp_path / "cells.lib"
    lib.write_liberty(out)
    back = {c.name for c in liberty.read_cells(out)}
    assert back == {n for n in lib.cells if lib.usable(n)}


def test_biblioteca_aponta_para_arquivo():
    with pytest.raises(LibraryError, match="aponte para a pasta"):
        Library(lib_path("cmos") / "library.json")


def test_familia_pelo_nome_ou_pela_pasta(tmp_path):
    assert Library("rtl").path == Library(lib_path("rtl")).path
    with pytest.raises(LibraryError, match="família 'nada' não encontrada"):
        Library("nada")
    # família própria fora do pacote, pela pasta
    shutil.copytree(lib_path("cmos"), tmp_path / "lib" / "minha")
    shutil.copy(LIB / "footprints.json", tmp_path / "lib")
    assert Library(tmp_path / "lib" / "minha").path == (tmp_path / "lib" / "minha").resolve()


def test_spice_elementos(tmp_path):
    f = tmp_path / "x.sp"
    f.write_text("""* comentário
.subckt CEL A B Y VDD GND
MP1 Y A VDD VDD PMOS
Q1 Y B GND BC548
R1 VDD Y 10k
C1 Y GND 100n
D1 GND A DIODE
K1 A GND Y VDD GND RELAY
X1 A
+ Y VDD GND INV
.ends CEL
""", encoding="utf-8")
    sub = spice.read_subckts(f)["CEL"]
    assert sub.pins == ["A", "B", "Y", "VDD", "GND"]
    kinds = {e.name: (e.letter, e.model) for e in sub.elements}
    assert kinds == {"MP1": ("M", "PMOS"), "Q1": ("Q", "BC548"), "R1": ("R", "R"), "C1": ("C", "C"),
                     "D1": ("D", "DIODE"), "K1": ("K", "RELAY"), "X1": ("X", "INV")}
    assert [e.nodes for e in sub.instances] == [["A", "Y", "VDD", "GND"]]     # continuação com +
    assert next(e for e in sub.elements if e.name == "R1").value == "10k"


@pytest.mark.parametrize("text, msg", [
    (".subckt A x\nL1 x y 1u\n.ends A\n", "não suportado"),
    (".subckt A x\n", "sem .ends"),
    (".ends A\n", ".ends sem .subckt"),
    (".subckt A x\nMP1 x y\n.ends A\n", "linha incompleta"),
])
def test_spice_recusa(tmp_path, text, msg):
    f = tmp_path / "bad.sp"
    f.write_text(text, encoding="utf-8")
    with pytest.raises(spice.SpiceError, match=msg):
        spice.read_subckts(f)


# --------------------------------------------------- simulação das montagens
@pytest.mark.tools
@pytest.mark.parametrize("family", FAMILIES)
def test_cellcheck_familia(family, tmp_path):
    assert cellcheck.check_cells(Library(lib_path(family)), tmp_path) == []


def _mutated(tmp_path, family, cell, old, new):
    dst = tmp_path / "lib" / family          # a família procura ../footprints.json
    shutil.copytree(lib_path(family), dst)
    shutil.copy(LIB / "footprints.json", tmp_path / "lib")
    sp = dst / "cells" / cell / f"{cell}.sp"
    text = sp.read_text(encoding="utf-8")
    assert old in text
    sp.write_text(text.replace(old, new, 1), encoding="utf-8")
    return Library(dst)


@pytest.mark.tools
@pytest.mark.parametrize("family, cell, old, new", [
    ("cmos", "NAND2", "MN2 n1 B GND GND NMOS", "MN2 n1 A GND GND NMOS"),     # NAND vira inversor de A
    ("cmos", "DLAT", "X1 D  E  sb", "X1 D  D  sb"),                          # latch sem enable
    ("rtl", "DLAT", "X1 D  eb r", "X1 eb D r"),                              # pinos trocados: mesma coisa (NOR comuta)
    ("relay", "DLAT", "K1 E GND x D Q RELAY", "K1 E GND x Q D RELAY"),       # contatos NA/NF trocados
    ("rtl", "TBUF", "R1  E   b1 10k", "R1  A   b1 10k"),                     # driver de barramento sem enable
])
def test_cellcheck_pega_montagem_errada(tmp_path, family, cell, old, new):
    fails = cellcheck.check_cells(_mutated(tmp_path, family, cell, old, new), tmp_path / "out")
    if (family, cell) == ("rtl", "DLAT"):
        assert fails == []          # controle: trocar as entradas de uma NOR não muda a função
    else:
        # a falha pode aparecer primeiro numa célula que usa esta (o DFF é feito de NAND2)
        assert fails and all(f.startswith("CELLFAIL") for f in fails), fails
