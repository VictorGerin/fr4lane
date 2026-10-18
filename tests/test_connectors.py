"""Conectores de E/S: pinagem, conectores automáticos, posição e validação."""

from types import SimpleNamespace

import pytest

from pcbflow import connectors, floorplan
from pcbflow.connectors import PITCH
from pcbflow.floorplan import FloorplanError

M = 4.0                                       # margem padrão da placa
GEO = SimpleNamespace(margin=M, x0=12.5, y_top0=6.0, io_gap=6.0, two=False)


def port(name, direction="input"):
    return SimpleNamespace(name=name, direction=direction, net=f"n_{name}")


PORTS = ([port(f"a[{i}]") for i in range(8)] + [port("ci"), port("en")]
         + [port(f"s[{i}]", "output") for i in range(4)] + [port("co", "output")])


def plan(conns):
    fp = floorplan.parse({"connectors": conns}, "fp.json")
    return connectors.plan(fp.connectors, PORTS, "VDD", "GND", GEO, "fp.json")


def labels(p):
    return [lbl for _, lbl in p.entries]


def test_sem_conectores_o_arranjo_de_sempre():
    ps = plan([])
    assert [(p.name, p.side, p.auto) for p in ps] == [("IN", "left", True), ("OUT", "right", True)]
    assert labels(ps[0]) == ["VDD", "GND"] + [f"a[{i}]" for i in range(8)] + ["ci", "en"]
    assert labels(ps[1]) == [f"s[{i}]" for i in range(4)] + ["co", "GND"]
    assert ps[0].at == ps[1].at == M + 1.27


def test_barramento_faixa_e_pinos_especiais():
    ps = plan([{"name": "J", "side": "top", "at": 20,
                "pins": ["VDD", "a[7:4]", "GND", "a[0]", "a[1:3]", "NC", "GND", "VDD"]}])
    j = ps[0]
    assert labels(j) == ["VDD", "a[7]", "a[6]", "a[5]", "a[4]", "GND", "a[0]", "a[1]", "a[2]", "a[3]",
                         "NC", "GND", "VDD"]
    assert j.entries[0][0] == "VDD" and j.entries[10][0] is None and j.entries[1][0] == "n_a[7]"
    # as portas usadas saem dos automáticos; VDD e GND já estão no J, mas ci/en ainda levam alimentação
    auto_in = next(p for p in ps if p.name == "IN")
    assert labels(auto_in) == ["VDD", "GND", "ci", "en"]


def test_sem_portas_sobrando_nao_ha_automatico():
    ps = plan([{"name": "J_IN", "side": "left", "pins": ["VDD", "GND", "a[*]", "ci", "en"]},
               {"name": "J_OUT", "side": "right", "pins": ["s[*]", "co", "GND"]}])
    assert [p.name for p in ps] == ["J_IN", "J_OUT"]


def test_nome_automatico_nao_repete_um_declarado():
    ps = plan([{"name": "IN", "side": "left", "pins": ["a[*]"]}])
    assert [p.name for p in ps] == ["IN", "IN2", "OUT"]


def test_posicao_automatica_depois_dos_declarados():
    ps = plan([{"name": "J1", "side": "left", "at": 30, "pins": ["a[*]"]},
               {"name": "J2", "side": "left", "pins": ["ci"]}])
    j1, j2, auto = ps[0], ps[1], next(p for p in ps if p.name == "IN")
    assert j2.at == pytest.approx(j1.end + 2 * PITCH)        # uma posição vazia entre as barras
    assert auto.at == pytest.approx(j2.end + 2 * PITCH)
    top = plan([{"name": "T", "side": "top", "pins": ["ci"]}])[0]
    assert top.at == GEO.x0                                  # em cima: começa na lógica, longe do canto


@pytest.mark.parametrize("pins, msg", [
    (["x"], "'x' não é uma porta do topo"),
    (["a"], "é um barramento"),
    (["x[*]"], "não há barramento 'x'"),
    (["a[9:6]"], "não tem o bit 9"),
    (["a[1]", "a[1:0]"], "já está no conector"),
    (["ci"] + ["GND"] * 40, "o máximo é 40"),
])
def test_pinagem_recusada(pins, msg):
    with pytest.raises(FloorplanError, match=msg.replace("[", r"\[").replace("]", r"\]")):
        plan([{"name": "J", "side": "left", "pins": pins}])


def test_porta_em_dois_conectores():
    with pytest.raises(FloorplanError, match="já está no conector 'J1'"):
        plan([{"name": "J1", "side": "left", "pins": ["ci"]}, {"name": "J2", "side": "top", "pins": ["ci"]}])


@pytest.mark.parametrize("conn, msg", [
    ({"name": "J", "side": "middle", "pins": ["ci"]}, "'side' deve ser"),
    ({"name": "J", "side": "left", "at": -1, "pins": ["ci"]}, "não pode ser negativo"),
    ({"name": "J", "side": "left", "pins": []}, "'pins' deve ser"),
    ({"side": "left", "pins": ["ci"]}, "falta 'name'"),
    ({"name": "J", "side": "left", "pins": ["ci"], "cor": 1}, "chave(s) desconhecida(s)"),
])
def test_formato_recusado(conn, msg):
    with pytest.raises(FloorplanError) as e:
        floorplan.parse({"connectors": [conn]}, "fp.json")
    assert msg in str(e.value)


def test_nome_repetido():
    with pytest.raises(FloorplanError, match="nome repetido"):
        floorplan.parse({"connectors": [{"name": "J", "side": "left", "pins": ["ci"]},
                                        {"name": "J", "side": "top", "pins": ["en"]}]})


def test_posicao_dos_pinos_em_cada_borda():
    ps = plan([{"name": "L", "side": "left", "at": 20, "pins": ["a[0]", "a[1]"]},
               {"name": "R", "side": "right", "at": 30, "pins": ["s[0]", "s[1]"]},
               {"name": "T", "side": "top", "at": 40, "pins": ["ci", "en"]},
               {"name": "B", "side": "bottom", "at": 50, "pins": ["co", "GND"]}])
    placed = {c.plan.name: c for c in connectors.place(ps, 120, 100, M)}
    near = M + 1.27
    assert placed["L"].pins == [(near, 20), (near, 20 + PITCH)]
    assert placed["R"].pins == [(120 - near, 30), (120 - near, 30 + PITCH)]
    assert placed["T"].pins == [(40, near), (40 + PITCH, near)] and placed["T"].horizontal
    assert placed["B"].pins == [(50, 100 - near), (50 + PITCH, 100 - near)]


def test_conector_fora_da_placa_ou_sobreposto():
    ps = plan([{"name": "B", "side": "bottom", "at": 110, "pins": ["co", "GND", "ci"]}])
    with pytest.raises(FloorplanError, match="'B' .* sai da placa"):
        connectors.place(ps, 112, 100, M)
    ps = plan([{"name": "L", "side": "left", "at": 6, "pins": ["a[*]"]},
               {"name": "T", "side": "top", "at": 6, "pins": ["ci"]}])
    with pytest.raises(FloorplanError, match="se sobrepõem"):
        connectors.place(ps, 120, 100, M)


def test_grade_abre_espaco_em_cima_e_embaixo():
    g = SimpleNamespace(**vars(GEO))
    connectors.apply_geo(g, plan([]))
    assert g.y_top == GEO.y_top0 and g.bottom_band == 0 and g.min_w == 0
    base_h = g.min_h
    g = SimpleNamespace(**vars(GEO))
    connectors.apply_geo(g, plan([{"name": "T", "side": "top", "at": 100, "pins": ["ci"]},
                                  {"name": "B", "side": "bottom", "pins": ["co"]}]))
    assert g.y_top > GEO.y_top0 and g.bottom_band > 0
    assert g.min_w > 100 and g.min_h > base_h
