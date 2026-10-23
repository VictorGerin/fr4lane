from types import SimpleNamespace
from fr4lane import floorplan, connectors, layout, backplane


def test_floorplan_custom_connector_types():
    fp = floorplan.parse({
        "connectors": [
            {"name": "BUS", "side": "bottom", "type": "card_edge", "pins": ["VDD", "GND", "clk"]},
            {"name": "PWR", "side": "left", "type": "screw_terminal", "pins": ["VDD", "GND"]},
            {"name": "IO", "side": "right", "type": "idc_box_header", "pins": ["d[1:0]"]},
            {"name": "DBG", "side": "top", "type": "pin_socket", "pins": ["NC"]},
        ]
    })
    assert len(fp.connectors) == 4
    assert fp.connectors[0].type == "card_edge"
    assert fp.connectors[1].type == "screw_terminal"
    assert fp.connectors[2].type == "idc_box_header"
    assert fp.connectors[3].type == "pin_socket"


def test_floorplan_mounting_holes():
    fp = floorplan.parse({
        "mounting_holes": [
            {"ref": "H1", "at": [5.0, 5.0], "size": "M3"},
            {"ref": "H2", "x": 95.0, "y": 5.0, "size": "M2.5"},
            [50.0, 50.0]
        ]
    })
    assert len(fp.mounting_holes) == 3
    assert fp.mounting_holes[0].ref == "H1"
    assert fp.mounting_holes[0].x == 5.0 and fp.mounting_holes[0].y == 5.0
    assert fp.mounting_holes[0].size == "M3"
    assert fp.mounting_holes[1].size == "M2.5"
    assert fp.mounting_holes[2].x == 50.0 and fp.mounting_holes[2].y == 50.0


def test_connectors_plan_preserves_type():
    fp = floorplan.parse({
        "connectors": [
            {"name": "CARD", "side": "bottom", "type": "card_edge", "pins": ["VDD", "GND", "clk"]}
        ]
    })
    ports = [SimpleNamespace(name="clk", net="n_clk", direction="input")]
    geo = SimpleNamespace(margin=4.0, x0=10.0)
    plans = connectors.plan(fp.connectors, ports, "n_vdd", "n_gnd", geo)
    assert len(plans) == 1
    assert plans[0].type == "card_edge"


def test_mating_map_resolution():
    assert backplane.MATING_MAP["card_edge"] == "card_edge_socket"
    assert backplane.MATING_MAP["pin_header"] == "pin_socket"
    assert backplane.MATING_MAP["pin_socket"] == "pin_header"
    assert backplane.MATING_MAP["screw_terminal"] == "screw_terminal"
