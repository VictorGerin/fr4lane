"""Conectores de E/S: pinagem e posição das barras de pinos (2,54 mm) nas bordas.

Os conectores do floorplan ("connectors", veja floorplan.py) fixam a borda, a
posição do pino 1 e a ordem dos pinos; as portas que nenhum deles lista vão
para os conectores automáticos, como sem floorplan: as entradas na borda
esquerda (depois de VDD e GND) e as saídas na direita (antes de um GND), em
barras de até 40 pinos.

A posição ao longo da borda ("at") é medida da borda de cima da placa (nos
conectores da esquerda e da direita) ou da esquerda (em cima e embaixo), e
não depende do tamanho da placa: o mesmo floorplan põe o conector no mesmo
lugar, o que permite casar os conectores de placas vizinhas. A distância até
a borda é sempre a mesma (o pino fica a margem + 1,27 mm da borda).

O placement (place.py) e o editor de floorplan (fpedit.py) usam estas mesmas
funções: o que o editor desenha é o que o fluxo monta.
"""

import re
from dataclasses import dataclass

from .floorplan import MAX_PINS, FloorplanError

PITCH = 2.54
HALF = 1.8                 # meia largura do contorno (courtyard) da barra de pinos
POWER = ("VDD", "GND")
NC = "NC"
_RANGE = re.compile(r"^(.+)\[(\d+):(\d+)\]$")
_BIT = re.compile(r"^(.+)\[(\d+)\]$")


@dataclass
class Plan:
    """Um conector antes de saber o tamanho da placa: a borda, o pino 1 ao longo
    dela e os pinos (net, rótulo); net None = pino sem ligação (NC)."""
    name: str
    side: str
    at: float
    entries: list
    auto: bool = False
    type: str = "pin_header"
    pitch: float = PITCH

    @property
    def end(self):
        """Posição do último pino ao longo da borda."""
        return self.at + (len(self.entries) - 1) * self.pitch


@dataclass
class Placed:
    """Um conector na placa: a posição de cada pino e o contorno."""
    plan: Plan
    pins: list             # [(x, y)] de cada pino, na ordem
    rect: tuple            # contorno (x0, y0, x1, y1)

    @property
    def horizontal(self):
        return self.plan.side in ("top", "bottom")


def _bus(ports):
    """{nome do barramento: {bit: porta}} e {nome: porta} das portas simples."""
    buses, scalars = {}, {}
    for p in ports:
        m = _BIT.match(p.name)
        if m:
            buses.setdefault(m.group(1), {})[int(m.group(2))] = p
        else:
            scalars[p.name] = p
    return buses, scalars


def _expand(text, buses, scalars, vdd, gnd, where):
    """Um texto de 'pins' -> [(net, rótulo)]."""
    if text == "VDD":
        return [(vdd, "VDD")]
    if text == "GND":
        return [(gnd, "GND")]
    if text == NC:
        return [(None, NC)]
    if text in scalars:
        p = scalars[text]
        return [(p.net, p.name)]
    if text.endswith("[*]"):
        name = text[:-3]
        if name not in buses:
            raise FloorplanError(f"{where}: '{text}': não há barramento '{name}' no topo")
        return [(p.net, p.name) for _, p in sorted(buses[name].items())]
    m = _RANGE.match(text)
    if m:
        name, a, b = m.group(1), int(m.group(2)), int(m.group(3))
        if name not in buses:
            raise FloorplanError(f"{where}: '{text}': não há barramento '{name}' no topo")
        step = -1 if a > b else 1
        out = []
        for bit in range(a, b + step, step):
            if bit not in buses[name]:
                raise FloorplanError(f"{where}: '{text}': o barramento '{name}' não tem o bit {bit}")
            p = buses[name][bit]
            out.append((p.net, p.name))
        return out
    m = _BIT.match(text)
    if m and m.group(1) in buses and int(m.group(2)) in buses[m.group(1)]:
        p = buses[m.group(1)][int(m.group(2))]
        return [(p.net, p.name)]
    hint = f" (é um barramento: use '{text}[*]' ou uma faixa como '{text}[7:0]')" if text in buses else ""
    raise FloorplanError(f"{where}: '{text}' não é uma porta do topo{hint}")


def select_ports(ports, names, where):
    """Portas citadas por uma lista no formato dos pinos dos conectores ("bus",
    "bus[*]", "bus[7:4]", "ack"): nomes dos bits. Um barramento pelo nome
    sozinho vale inteiro."""
    buses, scalars = _bus(ports)
    out = []
    for text in names:
        if text in buses and text not in scalars:
            text = f"{text}[*]"
        if text in POWER or text == NC:
            raise FloorplanError(f"{where}: '{text}' não é uma porta")
        for _, label in _expand(text, buses, scalars, None, None, where):
            if label not in out:
                out.append(label)
    return out


def starts(geo):
    """Onde começa o primeiro conector automático de cada borda: nas laterais,
    junto da borda de cima; em cima e embaixo, no início da lógica (longe dos
    cantos, onde ficam as colunas das laterais)."""
    first = geo.margin + 1.27
    return {"left": first, "right": first, "top": geo.x0, "bottom": geo.x0}


def plan(declared, ports, vdd, gnd, geo, source="floorplan"):
    """Os conectores do floorplan (com a pinagem resolvida) e os automáticos
    com as portas que sobraram. Sem conectores declarados, sai exatamente o
    arranjo de sempre: VDD, GND e as entradas à esquerda; as saídas e um GND à
    direita."""
    buses, scalars = _bus(ports)
    used = {}
    out = []
    for c in declared:
        where = f"{source}: conector '{c.name}'"
        entries = []
        for text in c.pins:
            for net, label in _expand(text, buses, scalars, vdd, gnd, where):
                if label not in POWER and label != NC:
                    if label in used:
                        raise FloorplanError(f"{where}: a porta '{label}' já está no conector '{used[label]}'")
                    used[label] = c.name
                entries.append((net, label))
        if len(entries) > MAX_PINS:
            raise FloorplanError(f"{where}: {len(entries)} pinos; o máximo é {MAX_PINS} por conector "
                                 "(divida em mais de um)")
        out.append(Plan(c.name, c.side, c.at, entries, auto=False,
                        type=getattr(c, "type", "pin_header"),
                        pitch=getattr(c, "pitch", PITCH)))

    labels = {e[1] for p in out for e in p.entries}
    inputs = [(p.net, p.name) for p in ports if p.direction == "input" and p.name not in used]
    outputs = [(p.net, p.name) for p in ports if p.direction != "input" and p.name not in used]
    left = inputs
    if inputs or "VDD" not in labels or "GND" not in labels:
        left = [(vdd, "VDD"), (gnd, "GND")] + inputs
    right = outputs + [(gnd, "GND")] if outputs else []
    taken = {c.name for c in declared}

    def auto_name(base):                 # IN, IN2, ...: sem repetir o nome de um declarado
        k = 1
        while (base if k == 1 else f"{base}{k}") in taken:
            k += 1
        name = base if k == 1 else f"{base}{k}"
        taken.add(name)
        return name

    for side, entries, base in (("left", left, "IN"), ("right", right, "OUT")):
        for k in range(0, len(entries), MAX_PINS):
            out.append(Plan(auto_name(base), side, None, entries[k:k + MAX_PINS], auto=True))

    # posição dos que não têm "at": depois do último da mesma borda, com uma
    # posição vazia entre eles (os contornos de duas barras não se tocam)
    first = starts(geo)
    for side in ("left", "right", "top", "bottom"):
        nxt = first[side]
        for p in out:
            if p.side == side and p.at is not None:
                nxt = max(nxt, p.end + 2 * PITCH)
        for p in out:
            if p.side == side and p.at is None:
                p.at = nxt
                nxt = p.end + 2 * PITCH
    return out


def bands(plans):
    """Bordas de cima e de baixo com conector (a lógica abre espaço para eles)."""
    sides = {p.side for p in plans}
    return "top" in sides, "bottom" in sides


def apply_geo(geo, plans):
    """Ajusta a grade (_Geo ou o geo do placement.json) aos conectores: a faixa
    deles em cima e embaixo e o tamanho mínimo da placa para caberem.
    Usa geo.y_top0 (o topo da lógica sem conectores em cima), geo.io_gap,
    geo.margin e geo.two."""
    top, bottom = bands(plans)
    band = PITCH + geo.io_gap
    geo.y_top = round((geo.margin + band + (0.5 if geo.two else 0.0)) / 0.5) * 0.5 if top else geo.y_top0
    geo.bottom_band = band if bottom else 0.0
    first = geo.margin + 1.27
    ends = {"left": first - PITCH, "right": first - PITCH}
    for p in plans:
        if p.side in ends:
            ends[p.side] = max(ends[p.side], p.end)
    # a coluna da esquerda leva o capacitor de bulk logo abaixo do último pino
    geo.min_h = max(ends["left"] + 5 * PITCH, ends["right"] + PITCH) + geo.margin + 4.0 + geo.bottom_band
    geo.io_h = max(ends["left"], ends["right"]) + PITCH - first
    x_end = max((p.end for p in plans if p.side in ("top", "bottom")), default=0.0)
    geo.min_w = x_end + HALF + 1.0 + HALF + PITCH / 2 + geo.margin if x_end else 0.0
    return geo


def bulk_y(plans, geo):
    """y do capacitor de bulk: na coluna da esquerda, abaixo do último pino."""
    ends = [p.end for p in plans if p.side == "left"]
    last = max(ends) if ends else geo.margin + 1.27 - PITCH
    return last + PITCH + 4.0


def place(plans, W, H, margin, source="floorplan"):
    """Posição dos pinos de cada conector numa placa W x H; erros (fora da
    placa, um sobre o outro) viram FloorplanError."""
    near = margin + 1.27
    placed = []
    for p in plans:
        if p.side == "left":
            pins = [(near, p.at + i * PITCH) for i in range(len(p.entries))]
        elif p.side == "right":
            pins = [(W - near, p.at + i * PITCH) for i in range(len(p.entries))]
        elif p.side == "top":
            pins = [(p.at + i * PITCH, near) for i in range(len(p.entries))]
        else:
            pins = [(p.at + i * PITCH, H - near) for i in range(len(p.entries))]
        xs, ys = [x for x, _ in pins], [y for _, y in pins]
        placed.append(Placed(p, pins, (min(xs) - HALF, min(ys) - HALF, max(xs) + HALF, max(ys) + HALF)))
    for c in placed:
        x0, y0, x1, y1 = c.rect
        if x0 < -1e-6 or y0 < -1e-6 or x1 > W + 1e-6 or y1 > H + 1e-6:
            raise FloorplanError(f"{source}: o conector '{c.plan.name}' ({c.plan.side}, pino 1 em "
                                 f"{c.plan.at:g} mm) sai da placa de {W:g} x {H:g} mm")
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            ra, rb = a.rect, b.rect
            if ra[0] < rb[2] and rb[0] < ra[2] and ra[1] < rb[3] and rb[1] < ra[3]:
                raise FloorplanError(f"{source}: os conectores '{a.plan.name}' e '{b.plan.name}' se sobrepõem")
    return placed
