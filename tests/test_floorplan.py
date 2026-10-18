"""Formato do floorplan: o que o fluxo aceita e o que recusa."""

import json

import pytest

from pcbflow import floorplan
from pcbflow.floorplan import FloorplanError


def test_floorplan_completo():
    fp = floorplan.parse({
        "_comment": "comentário preservado",
        "board": {"width": 160, "height": 120},
        "macros": ["adder"],
        "modules": {
            "u_fa": {"type": "fence", "rect": [20, 10, 60, 40], "decoupling": True},
            "u_fa.x": {"type": "region", "rect": [25, 15, 10, 10], "density": 0.8},   # dentro do pai: pode
            "u_dff": {"type": "guide", "near": [30, 90]},
        },
        "keepouts": [{"name": "furo", "rect": [0, 0, 8, 8], "what": ["route"], "layers": ["B.Cu"]}],
    }, "t.json")
    assert fp.board == (160.0, 120.0)
    assert fp.macros == ["adder"]
    assert fp.modules["u_fa"].rect == (20, 10, 80, 50) and fp.modules["u_fa"].decoupling
    assert fp.modules["u_fa.x"].density == 0.8
    assert fp.modules["u_dff"].rect == (30, 90, 30, 90)
    k = fp.keepouts[0]
    assert (k.name, k.rect, k.place, k.route, k.layers) == ("furo", (0, 0, 8, 8), False, True, ("B.Cu",))


def test_regra_mais_especifica_vale():
    fp = floorplan.parse({"modules": {"u0": {"type": "fence", "rect": [0, 0, 50, 50]},
                                      "u0.u1": {"type": "region", "rect": [1, 1, 10, 10]}}})
    assert fp.rule_of("u0.u1.x").path == "u0.u1"
    assert fp.rule_of("u0.u2").path == "u0"
    assert fp.rule_of("u9") is None


@pytest.mark.parametrize("data, msg", [
    ([], "esperado um objeto JSON"),
    ({"modulos": {}}, "chave(s) desconhecida(s)"),
    ({"macros": "adder"}, "'macros' deve ser uma lista"),
    ({"macros": [""]}, "'macros' deve ser uma lista"),
    ({"board": {"width": 0, "height": 10}}, "largura/altura <= 0"),
    ({"board": {"width": 10}}, "precisa de 'width' e 'height'"),
    ({"modules": {"a": {"type": "box", "rect": [0, 0, 1, 1]}}}, "'type' deve ser"),
    ({"modules": {"a": {"type": "fence"}}}, "falta 'rect'"),
    ({"modules": {"a": {"type": "fence", "rect": [0, 0, -1, 1]}}}, "largura/altura <= 0"),
    ({"modules": {"a": {"type": "fence", "rect": [0, 0, 1]}}}, "'rect' deve ser"),
    ({"modules": {"a": {"type": "fence", "near": [0, 0]}}}, "'near' só vale para 'guide'"),
    ({"modules": {"a": {"type": "guide", "rect": [0, 0, 1, 1], "density": 0.5}}}, "'density' só vale"),
    ({"modules": {"a": {"type": "fence", "rect": [0, 0, 1, 1], "density": 1.5}}}, "'density' deve ser"),
    ({"modules": {"a": {"type": "fence", "rect": [0, 0, 1, 1], "decoupling": "sim"}}}, "'decoupling' deve ser"),
    ({"modules": {"a": {"type": "fence", "rect": [0, 0, 10, 10]},
                  "b": {"type": "region", "rect": [5, 5, 10, 10]}}}, "se sobrepõem"),
    ({"keepouts": [{"rect": [0, 0, 1, 1], "what": ["drill"]}]}, "'what' deve conter"),
    ({"keepouts": [{"rect": [0, 0, 1, 1], "layers": ["In1.Cu"]}]}, "'layers' deve conter"),
    ({"board": {"width": 50, "height": 50}, "modules": {"a": {"type": "fence", "rect": [40, 0, 20, 5]}}},
     "sai da placa"),
])
def test_recusa(data, msg):
    with pytest.raises(FloorplanError) as e:
        floorplan.parse(data, "fp.json")
    assert msg in str(e.value)


def test_guide_pode_sobrepor():
    floorplan.parse({"modules": {"a": {"type": "fence", "rect": [0, 0, 10, 10]},
                                 "b": {"type": "guide", "rect": [5, 5, 10, 10]}}})


def test_load_arquivo(tmp_path):
    f = tmp_path / "x.floorplan.json"
    f.write_text(json.dumps({"modules": {"u": {"type": "fence", "rect": [0, 0, 5, 5]}}}), encoding="utf-8")
    assert "u" in floorplan.load(f).modules
    f.write_text("{ não é json", encoding="utf-8")
    with pytest.raises(FloorplanError):
        floorplan.load(f)
