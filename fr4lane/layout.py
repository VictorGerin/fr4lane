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
    rot: int = 0              # rotação no KiCad (graus); pads, contorno e serigrafia já vêm girados
    model: dict = None        # modelo 3D opcional do footprint: {"path": ..., "scale": [...], "offset": [...], "rotate": [...]}

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
    macro: bool = False  # cobre de um macro já roteado (copiado do molde)


@dataclass
class Via:
    x: float
    y: float
    net: str
    size: float
    drill: float
    uuid: str = field(default_factory=new_uuid)
    macro: bool = False  # cobre de um macro já roteado (copiado do molde)


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
                   silk=[tuple(s) for s in geo.get("silk", [])], tht=geo["type"] == "tht",
                   model=geo.get("model"))
    for p in geo["pads"]:
        fp.pads.append(Pad(p["num"], p["x"], p["y"], p["w"], p["h"], p.get("shape", "rect"),
                           tht=geo["type"] == "tht", drill=p.get("drill", 0.0), fp=fp))
    return fp


def pin_header(ref, n_pins, value="", horizontal=False):
    """Barra de pinos 1xN, 2.54 mm (mesma geometria da biblioteca do KiCad).
    horizontal: deitada, com os pinos para a direita (o footprint da biblioteca
    girado 90°; a geometria aqui já vem girada, o kicad.py escreve a rotação)."""
    lib_name = f"Connector_PinHeader_2.54mm:PinHeader_1x{n_pins:02d}_P2.54mm_Vertical"
    span = (n_pins - 1) * 2.54
    courtyard = (-1.8, -1.8, span + 1.8, 1.8) if horizontal else (-1.8, -1.8, 1.8, span + 1.8)
    fp = Footprint(ref, value or f"Conn_01x{n_pins:02d}", lib_name, courtyard=courtyard, tht=True,
                   rot=90 if horizontal else 0)
    for i in range(n_pins):
        shape = "rect" if i == 0 else "oval"
        rx, ry = (i * 2.54, 0.0) if horizontal else (0.0, i * 2.54)
        fp.pads.append(Pad(str(i + 1), rx, ry, 1.7, 1.7, shape, tht=True, drill=1.0, fp=fp))
    fp.silk = [(-1.33, -1.33, -1.33, 1.33)] if horizontal else [(-1.33, -1.33, 1.33, -1.33)]
    return fp


def pin_socket(ref, n_pins, value="", horizontal=False):
    """Barra de soquetes fêmea 1xN, 2.54 mm (KiCad Connector_PinSocket_2.54mm).
    Mating connector padrão para barras de pinos macho."""
    lib_name = f"Connector_PinSocket_2.54mm:PinSocket_1x{n_pins:02d}_P2.54mm_Vertical"
    span = (n_pins - 1) * 2.54
    courtyard = (-1.8, -1.8, span + 1.8, 1.8) if horizontal else (-1.8, -1.8, 1.8, span + 1.8)
    fp = Footprint(ref, value or f"Socket_01x{n_pins:02d}", lib_name, courtyard=courtyard, tht=True,
                   rot=90 if horizontal else 0)
    for i in range(n_pins):
        shape = "rect" if i == 0 else "oval"
        rx, ry = (i * 2.54, 0.0) if horizontal else (0.0, i * 2.54)
        fp.pads.append(Pad(str(i + 1), rx, ry, 1.7, 1.7, shape, tht=True, drill=1.0, fp=fp))
    fp.silk = [(-1.33, -1.33, -1.33, 1.33)] if horizontal else [(-1.33, -1.33, 1.33, -1.33)]
    return fp


def card_edge_fingers(ref, n_pins, value="", pitch=2.54, horizontal=False):
    """Dedos de ouro (Gold Fingers) para borda da PCB. Pads SMD chanfrados."""
    lib_name = f"Connector_PCBEdge:CardEdge_1x{n_pins:02d}_P{pitch:.2f}mm_Fingers"
    span = (n_pins - 1) * pitch
    # No sentido horizontal (borda top/bottom), conector corre em X e pads alongam em Y (7mm)
    # No vertical (borda left/right), conector corre em Y e pads alongam em X (7mm)
    pw, ph = (1.5, 7.0) if horizontal else (7.0, 1.5)
    courtyard = (-1.0, -4.0, span + 1.0, 4.0) if horizontal else (-4.0, -1.0, 4.0, span + 1.0)
    fp = Footprint(ref, value or f"GoldFingers_1x{n_pins:02d}", lib_name, courtyard=courtyard, tht=False,
                   rot=90 if horizontal else 0)
    for i in range(n_pins):
        rx, ry = (i * pitch, 0.0) if horizontal else (0.0, i * pitch)
        fp.pads.append(Pad(str(i + 1), rx, ry, pw, ph, "roundrect", tht=False, fp=fp))
    # Linha guia do chanfro da borda (bevel) na serigrafia
    fp.silk = [(-1.0, 3.5, span + 1.0, 3.5)] if horizontal else [(3.5, -1.0, 3.5, span + 1.0)]
    return fp


def card_edge_socket(ref, n_pins, value="", pitch=2.54, horizontal=False):
    """Slot receptor fêmea para Card Edge (dedos de ouro) no Backplane."""
    lib_name = f"Connector_PCBEdge:CardEdge_1x{n_pins:02d}_P{pitch:.2f}mm_Socket"
    span = (n_pins - 1) * pitch
    courtyard = (-4.5, -2.5, span + 4.5, 2.5) if horizontal else (-2.5, -4.5, 2.5, span + 4.5)
    fp = Footprint(ref, value or f"CardEdgeSocket_1x{n_pins:02d}", lib_name, courtyard=courtyard, tht=True,
                   rot=90 if horizontal else 0)
    for i in range(n_pins):
        shape = "rect" if i == 0 else "oval"
        rx, ry = (i * pitch, 0.0) if horizontal else (0.0, i * pitch)
        fp.pads.append(Pad(str(i + 1), rx, ry, 1.8, 1.8, shape, tht=True, drill=1.1, fp=fp))
    # Contorno plástico do slot fêmea
    bw = 8.0
    fp.silk = [
        (-3.0, -bw / 2, span + 3.0, -bw / 2),
        (span + 3.0, -bw / 2, span + 3.0, bw / 2),
        (span + 3.0, bw / 2, -3.0, bw / 2),
        (-3.0, bw / 2, -3.0, -bw / 2),
    ] if horizontal else [
        (-bw / 2, -3.0, -bw / 2, span + 3.0),
        (-bw / 2, span + 3.0, bw / 2, span + 3.0),
        (bw / 2, span + 3.0, bw / 2, -3.0),
        (bw / 2, -3.0, -bw / 2, -3.0),
    ]

    # Modelo 3D mapeado para a biblioteca oficial do KiCad (Connector_PinSocket_2.54mm)
    m_pins = min(n_pins, 40)
    scl_y = 1.0 if n_pins <= 40 else round(((n_pins - 1) * pitch) / (39.0 * 2.54), 4)
    fp.model = {
        "path": f"${{KICAD_3DMODEL_DIR}}/Connector_PinSocket_2.54mm.3dshapes/PinSocket_1x{m_pins:02d}_P2.54mm_Vertical.step",
        "offset": (0.0, 0.0, 0.0),
        "scale": (1.0, scl_y, 1.0),
        "rotate": (0.0, 0.0, 0.0),
    }
    return fp


def screw_terminal_block(ref, n_pins, value="", pitch=5.08, horizontal=False):
    """Bloco terminal a parafuso (Phoenix MKDS ou compatível)."""
    lib_name = f"TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-{n_pins}-5.08_1x{n_pins:02d}_P5.08mm_Horizontal"
    span = (n_pins - 1) * pitch
    courtyard = (-2.5, -4.5, span + 2.5, 4.5) if horizontal else (-4.5, -2.5, 4.5, span + 2.5)
    fp = Footprint(ref, value or f"TerminalBlock_1x{n_pins:02d}", lib_name, courtyard=courtyard, tht=True,
                   rot=90 if horizontal else 0)
    for i in range(n_pins):
        shape = "rect" if i == 0 else "oval"
        rx, ry = (i * pitch, 0.0) if horizontal else (0.0, i * pitch)
        fp.pads.append(Pad(str(i + 1), rx, ry, 3.2, 3.2, shape, tht=True, drill=1.3, fp=fp))
    fp.silk = [
        (-2.5, -4.0, span + 2.5, -4.0),
        (span + 2.5, -4.0, span + 2.5, 4.0),
        (span + 2.5, 4.0, -2.5, 4.0),
        (-2.5, 4.0, -2.5, -4.0),
    ] if horizontal else [
        (-4.0, -2.5, -4.0, span + 2.5),
        (-4.0, span + 2.5, 4.0, span + 2.5),
        (4.0, span + 2.5, 4.0, -2.5),
        (4.0, -2.5, -4.0, -2.5),
    ]
    return fp


def idc_box_header(ref, n_pins, value="", horizontal=False):
    """Conector IDC com trava plástica (Shrouded Box Header 2xN)."""
    rows = 2
    cols = n_pins // rows
    pitch = 2.54
    lib_name = f"Connector_IDC:IDC-Header_2x{cols:02d}_P2.54mm_Vertical"
    span = (cols - 1) * pitch
    courtyard = (-3.5, -4.5, span + 3.5, 4.5)
    fp = Footprint(ref, value or f"IDC_Header_2x{cols:02d}", lib_name, courtyard=courtyard, tht=True,
                   rot=90 if horizontal else 0)
    pad_idx = 1
    for c in range(cols):
        for r in range(rows):
            rx = c * pitch
            ry = (r - 0.5) * pitch
            shape = "rect" if pad_idx == 1 else "oval"
            fp.pads.append(Pad(str(pad_idx), rx, ry, 1.7, 1.7, shape, tht=True, drill=1.0, fp=fp))
            pad_idx += 1
    # Caixa plástica do conector
    fp.silk = [
        (-3.0, -4.0, span + 3.0, -4.0),
        (span + 3.0, -4.0, span + 3.0, 4.0),
        (span + 3.0, 4.0, -3.0, 4.0),
        (-3.0, 4.0, -3.0, -4.0),
    ]
    return fp


def mounting_hole(ref, x, y, size="M3"):
    """Furo de fixação com parafuso (M2.5, M3, M4)."""
    drill_map = {"M2.5": 2.7, "M3": 3.2, "M4": 4.3}
    drill = drill_map.get(size.upper(), 3.2)
    lib_name = f"MountingHole:MountingHole_{drill:.1f}mm_{size.upper()}"
    fp = Footprint(ref, size.upper(), lib_name, x=x, y=y, courtyard=(-3.0, -3.0, 3.0, 3.0), tht=True)
    fp.pads.append(Pad("1", 0.0, 0.0, drill, drill, "circle", tht=True, drill=drill, fp=fp))
    return fp
