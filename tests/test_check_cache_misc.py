"""Verificação de folgas/conectividade numa placa feita à mão, cache das
rodadas e utilitários pequenos."""

import pytest

from pcbflow import cache, check, drive, netlist, progress
from pcbflow.floorplan import Floorplan, Keepout
from pcbflow.layout import Board, Footprint, Pad, Track, Via


def _board(tracks=(), vias=(), layers=2):
    fps = []
    for ref, x in (("U1", 10.0), ("U2", 20.0)):
        fp = Footprint(ref, "X", "X", x, 10.0, courtyard=(-1, -1, 1, 1))
        fp.pads.append(Pad("1", 0, 0, 1.0, 1.0, "rect", net="a", fp=fp))
        fps.append(fp)
    b = Board(40, 20, fps, "VDD", "GND", layers=layers)
    b.tracks, b.vias = list(tracks), list(vias)
    return b


def test_placa_ligada_e_sem_folga():
    errors, unconnected = check.check_board(_board([Track(10, 10, 20, 10, "F.Cu", "a", 0.25)]))
    assert errors == [] and unconnected == {}


def test_net_aberta():
    errors, unconnected = check.check_board(_board())
    assert errors == [] and unconnected == {"a": 2}


def test_trilha_de_outra_net_perto_demais():
    tr = [Track(10, 10, 20, 10, "F.Cu", "a", 0.25), Track(5, 10.75, 25, 10.75, "F.Cu", "b", 0.25)]
    errors, _ = check.check_board(_board(tr))
    assert errors and "folga" in errors[0] and "[b]" in " ".join(errors)


def test_camadas_diferentes_nao_colidem():
    # trilha de outra net na B.Cu por cima de pads SMD (F.Cu): sem violação
    tr = [Track(10, 10, 20, 10, "F.Cu", "a", 0.25), Track(5, 10, 25, 10, "B.Cu", "b", 0.25)]
    assert check.check_board(_board(tr))[0] == []


def test_via_liga_camadas():
    tr = [Track(10, 10, 15, 10, "F.Cu", "a", 0.25), Track(15, 10, 15, 15, "B.Cu", "a", 0.25),
          Track(15, 15, 15, 10, "B.Cu", "a", 0.25), Track(15, 10, 20, 10, "F.Cu", "a", 0.25)]
    ok = check.check_board(_board(tr, [Via(15, 10, "a", 0.6, 0.3)]))
    assert ok == ([], {})


def test_keepout_de_trilha():
    b = _board([Track(10, 10, 20, 10, "F.Cu", "a", 0.25)])
    b.floorplan = Floorplan("fp")
    b.keepouts = [Keepout("k", (14, 9, 16, 11), False, True, ("F.Cu",))]
    b.floorplan.keepouts = b.keepouts
    errors, _ = check.check_board(b)
    assert any("keepout de roteamento 'k'" in e for e in errors), errors


# ------------------------------------------------------------------ cache
KEY = {"src": "s1", "lib": "l1", "floorplan": None, "args": "a1", "code": "c1"}


def test_cache_ida_e_volta(tmp_path):
    cache.save(tmp_path, KEY, board="placa", sims={"x": (True, True)})
    got, why = cache.load(tmp_path, KEY)
    assert why is None and got["board"] == "placa" and got["sims"] == {"x": (True, True)}


def test_cache_entrada_diferente(tmp_path):
    cache.save(tmp_path, KEY, board="placa")
    got, why = cache.load(tmp_path, dict(KEY, src="s2"))
    assert got is None and why.startswith("mudou")


def test_cache_ignora_codigo_com_keep_placement(tmp_path):
    cache.save(tmp_path, KEY, board="placa")
    assert cache.load(tmp_path, dict(KEY, code="c2"))[0] is None
    assert cache.load(tmp_path, dict(KEY, code="c2"), ignore=("code",))[0]["board"] == "placa"


def test_cache_inexistente_ou_corrompido(tmp_path):
    assert cache.load(tmp_path, KEY) == (None, None)
    (tmp_path / cache.FILE).write_bytes(b"lixo")
    got, why = cache.load(tmp_path, KEY)
    assert got is None and "ilegível" in why


# --------------------------------------------------------------- utilitários
@pytest.mark.parametrize("s, v", [("10k", 10e3), ("4k7", 4.7e3), ("100n", 100e-9), ("4.7u", 4.7e-6),
                                  ("2M", 2e-3),          # convenção SPICE: M é mili; mega é meg
                                  ("470", 470.0), ("1meg", 1e6), ("1kohm", 1e3)])
def test_parse_value(s, v):
    assert drive.parse_value(s) == pytest.approx(v)


def test_parse_value_invalido():
    with pytest.raises(ValueError):
        drive.parse_value("dez")


@pytest.mark.parametrize("s, txt", [(5, "5 s"), (65, "1 min 05 s"), (3725, "1 h 02 min")])
def test_fmt_time(s, txt):
    assert progress.fmt_time(s) == txt


def test_scope_of():
    assert netlist.scope_of("$flatten\\u_fa.$abc$198$new_n7") == "u_fa"
    assert netlist.scope_of("u_a.u_b.g1") == "u_a.u_b"
    assert netlist.scope_of("g1") == ""
