"""macro_keepout: nenhuma rota de fora por cima dos macros (roteador, verificação,
floorplan e o fluxo de verdade com o hier8)."""

import json
import re

import pytest

from conftest import data, lib_path, run_flow
from pcbflow import check, floorplan
from pcbflow.layout import Board, Footprint, Pad, Track, Via
from pcbflow.route import BLOCK, FREE, Router

MACRO = (5.0, 5.0, 15.0, 15.0)


def _board(keepout):
    """Placa 20 x 20 mm com um macro no meio e o pino da net n1 na borda esquerda dele."""
    b = Board(20, 20, [], "VDD", "GND")
    b.macro_rects = [MACRO]
    b.pins = [("n1", 5.0, 10.0, 0)]
    b.macro_keepout = keepout
    return b


def test_roteador_bloqueia_o_interior_do_macro():
    rt = Router(_board(True), log=lambda m: None, edge=False)
    g = rt.g
    center = rt.node(0, int(10 / g), int(10 / g))
    assert rt.static[center] == BLOCK and rt.static[center + rt.nxy] == BLOCK
    assert rt.via_static[int(10 / g) * rt.nx + int(10 / g)] == BLOCK
    # o pino, na borda, continua sendo a porta de entrada; o canal de fora fica livre
    assert rt.static[rt.node(0, int(5 / g), int(10 / g))] == rt.net_id["n1"]
    assert rt.static[rt.node(1, int(3 / g), int(10 / g))] == FREE


def test_sem_a_opcao_o_interior_fica_livre():
    rt = Router(_board(False), log=lambda m: None, edge=False)
    assert rt.static[rt.node(0, int(10 / rt.g), int(10 / rt.g))] == FREE


def _check_board(keepout, track, via=None):
    fp = Footprint("U1", "X", "X", 2.0, 2.0, courtyard=(-1, -1, 1, 1))
    fp.pads.append(Pad("1", 0, 0, 1.0, 1.0, "rect", net="a", fp=fp))
    b = Board(20, 20, [fp], "VDD", "GND")
    b.tracks = [track]
    b.vias = [via] if via else []
    b.macro_rects = [MACRO]
    b.macro_keepout = keepout
    return b


def test_verificacao_acusa_trilha_de_fora_no_macro():
    errors, _ = check.check_board(_check_board(True, Track(2, 10, 18, 10, "F.Cu", "x", 0.25)))
    assert any(e.startswith("macro: trilha") for e in errors), errors
    errors, _ = check.check_board(_check_board(True, Track(2, 2, 2, 18, "B.Cu", "x", 0.25),
                                               Via(10, 10, "y", 0.6, 0.3)))
    assert [e for e in errors if e.startswith("macro:")] == [next(e for e in errors if "via" in e)]


def test_verificacao_aceita_o_cobre_do_macro_e_a_chegada_no_pino():
    t = Track(6, 10, 14, 10, "F.Cu", "x", 0.25, macro=True)
    assert not [e for e in check.check_board(_check_board(True, t))[0] if e.startswith("macro:")]
    t = Track(1, 10, 5, 10, "F.Cu", "x", 0.25)          # termina no pino, na borda
    assert not [e for e in check.check_board(_check_board(True, t))[0] if e.startswith("macro:")]
    t = Track(2, 10, 18, 10, "F.Cu", "x", 0.25)         # sem a opção, atravessar pode
    assert not [e for e in check.check_board(_check_board(False, t))[0] if e.startswith("macro:")]


def test_floorplan_aceita_e_valida():
    fp = floorplan.parse({"macros": ["a"], "macro_keepout": True, "macro_channel": 4})
    assert fp.macro_keepout is True and fp.macro_channel == 4.0
    fp = floorplan.parse({})
    assert fp.macro_keepout is False and fp.macro_channel is None
    with pytest.raises(floorplan.FloorplanError, match="'macro_keepout' deve ser true ou false"):
        floorplan.parse({"macro_keepout": "sim"})
    for bad in (0.2, 80, True, "4"):
        with pytest.raises(floorplan.FloorplanError, match="'macro_channel' deve ser"):
            floorplan.parse({"macro_channel": bad})


@pytest.mark.slow
def test_fluxo_sem_rotas_por_cima_dos_macros(tmp_path):
    """hier8 com add4 como macro: a placa fecha e nenhuma trilha ou via do
    roteamento de cima fica dentro de um macro (a etapa 5 confere)."""
    r = run_flow(tmp_path / "out", "--top", "hier8", "--src", data("hier8.v"), "--lib", lib_path("rtl"),
                 "--no-drc", "--macro", "add4", "--macro-keepout", "--fresh")
    assert "sem rotas de fora por cima deles" in r.log, r
    assert re.search(r"violações de folga: 0\b", r.log), r
    assert re.search(r"nets incompletas: 0\b", r.log), r


@pytest.mark.slow
def test_canal_dos_macros_afasta_e_editor_preve(tmp_path):
    """"macro_channel" alarga o canal em volta de cada macro, e o editor (mesma
    função do hier.py) prevê a posição com o canal do floorplan."""
    from pcbflow import fpedit
    fpf = tmp_path / "hier8.floorplan.json"
    fpd = {"macros": ["add4"], "macro_channel": 4}
    fpf.write_text(json.dumps(fpd), encoding="utf-8")
    r = run_flow(tmp_path / "out", "--top", "hier8", "--src", data("hier8.v"), "--lib", lib_path("rtl"),
                 "--no-drc", "--floorplan", fpf, "--place-only", "--fresh")
    assert r.rc == 0 and "canal de 4 mm" in r.log, r
    run = r.placement()
    m = run["macros"]
    assert m["ring"] == 4
    for path in ("lo", "hi"):
        x0, y0, x1, y1 = m["instances"][path]["rect"]
        ox, oy = m["instances"][path]["origin"]
        t = m["templates"][m["instances"][path]["template"]]
        assert ox - x0 == pytest.approx(4, abs=0.5) and x1 - (ox + t["w"]) == pytest.approx(4, abs=0.01)
    pred = fpedit.check(fpd, run, fpf.name)
    assert pred["macros"]["ring"] == 4
    for i in pred["macros"]["instances"]:
        assert i["origin"] == m["instances"][i["path"]]["origin"], i["path"]
