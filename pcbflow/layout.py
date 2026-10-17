"""Modelo físico da placa (footprints, pads, trilhas, vias) independente do KiCad."""

import math
import uuid
from dataclasses import dataclass, field


def new_uuid():
    return str(uuid.uuid4())


@dataclass
class Pad:
    num: str
    rx: float            # posição relativa à origem do footprint
    ry: float
    w: float
    h: float
    shape: str           # rect | roundrect | oval | circle
    tht: bool = False
    drill: float = 0.0
    net: str = ""
    function: str = ""
    fp: "Footprint" = None
    macro: bool = False  # pad de um macro já roteado: o roteador de cima o trata só como obstáculo

    @property
    def x(self):
        return self.fp.x + self.rx

    @property
    def y(self):
        return self.fp.y + self.ry

    def bbox(self):
        return (self.x - self.w / 2, self.y - self.h / 2, self.x + self.w / 2, self.y + self.h / 2)

    def corner_radius(self):
        """Raio dos cantos do cobre: circle/oval arredondam o lado menor inteiro,
        roundrect usa a mesma proporção (0,25) que o kicad.py escreve."""
        m = min(self.w, self.h)
        return {"circle": m / 2, "oval": m / 2, "roundrect": 0.25 * m}.get(self.shape, 0.0)

    def dist(self, px, py):
        """Distância de um ponto ao cobre do pad, pela forma real (0 dentro dele).
        O retângulo envolvente não serve: no canto de um pad oval não há cobre."""
        r = self.corner_radius()
        dx = max(abs(px - self.x) - (self.w / 2 - r), 0.0)
        dy = max(abs(py - self.y) - (self.h / 2 - r), 0.0)
        return max(0.0, math.hypot(dx, dy) - r)

    def seg_dist(self, x1, y1, x2, y2):
        """Distância de um segmento (o eixo de uma trilha) ao cobre do pad. A
        distância a um convexo é convexa ao longo da reta: busca ternária."""
        f = lambda t: self.dist(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
        a, b = 0.0, 1.0
        for _ in range(40):
            m1, m2 = a + (b - a) / 3, b - (b - a) / 3
            if f(m1) <= f(m2):
                b = m2
            else:
                a = m1
        return min(f(0.0), f(1.0), f((a + b) / 2))

    @property
    def layers(self):
        return ("F.Cu", "B.Cu") if self.tht else ("F.Cu",)


@dataclass
class Footprint:
    ref: str
    value: str
    lib_name: str
    x: float = 0.0
    y: float = 0.0
    pads: list = field(default_factory=list)
    courtyard: tuple = (-1, -1, 1, 1)
    silk: list = field(default_factory=list)
    tht: bool = False
    group: str = ""
    uuid: str = field(default_factory=new_uuid)

    def pad(self, num):
        for p in self.pads:
            if p.num == num:
                return p
        raise KeyError(num)


@dataclass
class Track:
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str
    net: str
    width: float
    uuid: str = field(default_factory=new_uuid)


@dataclass
class Via:
    x: float
    y: float
    net: str
    size: float
    drill: float
    uuid: str = field(default_factory=new_uuid)


@dataclass
class Rules:
    grid: float = 0.5
    track_width: float = 0.25
    clearance: float = 0.2
    via_size: float = 0.6
    via_drill: float = 0.3
    edge_clearance: float = 0.5


@dataclass
class Board:
    width: float
    height: float
    footprints: list
    vdd: str
    gnd: str
    rules: Rules = field(default_factory=Rules)
    tracks: list = field(default_factory=list)
    vias: list = field(default_factory=list)
    groups: dict = field(default_factory=dict)       # nome -> [uuids]
    layers: int = 4                                  # 4: planos de VDD/GND; 2: trilhos
    floorplan: object = None                         # floorplan.Floorplan declarado (ou None)
    keepouts: list = field(default_factory=list)     # floorplan.Keepout
    unrouted: list = field(default_factory=list)

    def nets(self):
        names = {p.net for fp in self.footprints for p in fp.pads if p.net}
        power = [n for n in (self.gnd, self.vdd) if n in names]
        return power + sorted(names - set(power))

    def pads(self):
        return [p for fp in self.footprints for p in fp.pads]


def footprint_from_library(lib, lib_name, ref, value):
    geo = lib.footprints[lib_name]
    fp = Footprint(ref, value, lib_name, courtyard=tuple(geo["courtyard"]),
                   silk=[tuple(s) for s in geo.get("silk", [])], tht=geo["type"] == "tht")
    for p in geo["pads"]:
        fp.pads.append(Pad(p["num"], p["x"], p["y"], p["w"], p["h"], p.get("shape", "rect"),
                           tht=geo["type"] == "tht", drill=p.get("drill", 0.0), fp=fp))
    return fp


def pin_header(ref, n_pins, value=""):
    """Barra de pinos 1xN, 2.54 mm (mesma geometria da biblioteca do KiCad)."""
    lib_name = f"Connector_PinHeader_2.54mm:PinHeader_1x{n_pins:02d}_P2.54mm_Vertical"
    fp = Footprint(ref, value or f"Conn_01x{n_pins:02d}", lib_name,
                   courtyard=(-1.8, -1.8, 1.8, (n_pins - 1) * 2.54 + 1.8), tht=True)
    for i in range(n_pins):
        shape = "rect" if i == 0 else "oval"
        fp.pads.append(Pad(str(i + 1), 0.0, i * 2.54, 1.7, 1.7, shape, tht=True, drill=1.0, fp=fp))
    fp.silk = [(-1.33, -1.33, 1.33, -1.33)]
    return fp
