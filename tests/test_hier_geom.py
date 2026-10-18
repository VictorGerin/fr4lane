"""Geometria do fluxo hierárquico: onde cada macro fica e o floorplan da
lógica solta (as mesmas funções que o fpedit usa para prever a placa)."""

from types import SimpleNamespace

import pytest

from pcbflow import floorplan, hier
from pcbflow.floorplan import FloorplanError

G = 0.5
GEO = SimpleNamespace(x0=12.5, y_top=6.0)
R = hier.RING


def test_top_macros():
    mods = {"u0": "add16", "u0.u0": "add4", "u0.u1": "add4", "u1": "add16", "u1.u0": "add4", "x": "mux"}
    assert hier.top_macros(mods, ["add4"]) == (["u0.u0", "u0.u1", "u1.u0"], ["u0.u0", "u0.u1", "u1.u0"])
    paths, top = hier.top_macros(mods, ["add4", "add16"])
    assert top == ["u0", "u1"] and "u0.u1" in paths


def test_pack_prateleiras():
    out = hier._pack([(10, 5), (10, 8), (10, 5)], 0, 0, 30, G)
    (ox0, oy0, r0), (ox1, oy1, r1), (ox2, oy2, r2) = out
    assert (ox0, oy0) == (R, R)
    assert r1[0] == r0[2] and oy1 == oy0                    # lado a lado
    assert ox2 == R and r2[1] == max(r0[3], r1[3])          # 3º não cabe: nova prateleira
    for ox, oy, r in out:                                  # canal em volta e grade
        assert ox - r[0] == pytest.approx(R) and ox % G == 0 and oy % G == 0


def _boxes(*paths, w=20, h=10, typ="m"):
    return {p: (typ, w, h) for p in paths}


def test_sem_floorplan_empacota_no_topo():
    spot = hier.macro_spots(["a", "b"], _boxes("a", "b"), None, GEO, 0.0, G)
    assert spot["a"][0] >= GEO.x0 and spot["a"][1] >= GEO.y_top
    assert not floorplan.overlap(spot["a"][2], spot["b"][2])


def test_fence_da_instancia_poe_o_macro_no_canto():
    fp = floorplan.parse({"modules": {"a": {"type": "fence", "rect": [100, 50, 30, 20]}}})
    spot = hier.macro_spots(["a"], _boxes("a"), fp, GEO, 0.0, G)
    assert spot["a"] == (101.5, 51.5, (100, 50, 130, 70))


def test_fence_pequena():
    fp = floorplan.parse({"modules": {"a": {"type": "fence", "rect": [100, 50, 20, 10]}}}, "fp.json")
    with pytest.raises(FloorplanError, match="não comporta o macro m"):
        hier.macro_spots(["a"], _boxes("a"), fp, GEO, 0.0, G)
    # com errors (modo do editor): vira mensagem e o macro é posicionado assim mesmo
    errs = []
    spot = hier.macro_spots(["a"], _boxes("a"), fp, GEO, 0.0, G, errors=errs)
    assert len(errs) == 1 and spot["a"][:2] == (101.5, 51.5)


def test_macros_dentro_da_area_do_pai():
    fp = floorplan.parse({"modules": {"u0": {"type": "fence", "rect": [0, 0, 100, 40]}}})
    spot = hier.macro_spots(["u0.a", "u0.b"], _boxes("u0.a", "u0.b"), fp, GEO, 0.0, G)
    for p in ("u0.a", "u0.b"):
        assert floorplan.contains((0, 0, 100, 40), spot[p][2])
    fp = floorplan.parse({"modules": {"u0": {"type": "fence", "rect": [0, 0, 30, 15]}}})
    with pytest.raises(FloorplanError, match="não cabem na área"):
        hier.macro_spots(["u0.a", "u0.b"], _boxes("u0.a", "u0.b"), fp, GEO, 0.0, G)


def test_macro_solto_vai_abaixo_das_areas():
    fp = floorplan.parse({"modules": {"z": {"type": "fence", "rect": [0, 0, 50, 80]}},
                          "keepouts": [{"rect": [60, 0, 10, 120]}]})
    spot = hier.macro_spots(["a"], _boxes("a"), fp, GEO, 0.0, G)
    assert spot["a"][2][1] >= 120


def test_glue_floorplan():
    fp = floorplan.parse({"modules": {
        "u0": {"type": "fence", "rect": [0, 0, 100, 40]},         # só macros dentro: vira keepout
        "u1": {"type": "fence", "rect": [0, 50, 100, 40]},        # tem lógica solta: continua
        "u0.a": {"type": "fence", "rect": [1, 1, 30, 20]},        # área de macro: sai
    }, "keepouts": [{"name": "k", "rect": [200, 0, 5, 5]}]})
    spot = {"u0.a": (2.5, 2.5, (1, 1, 31, 21))}
    syn = hier.glue_floorplan(fp, ["u0.a"], {"u1", "u1.x"}, ["u0.a"], spot)
    assert set(syn.modules) == {"u1"}
    names = {k.name for k in syn.keepouts}
    assert names == {"área de u0", "k", "macro u0.a"}
    assert all(k.place and not k.route for k in syn.keepouts if k.name != "k")
