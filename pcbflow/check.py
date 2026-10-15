"""Verificação independente da placa gerada: folgas (DRC simplificado) e
conectividade por net. Não substitui o DRC do KiCad, mas pega erros do
próprio roteador antes de abrir o projeto."""

import math
from collections import defaultdict


def _rect_dist(a, b):
    dx = max(0.0, a[0] - b[2], b[0] - a[2])
    dy = max(0.0, a[1] - b[3], b[1] - a[3])
    return math.hypot(dx, dy)


class _Item:
    __slots__ = ("kind", "net", "layers", "rect", "half", "ref")

    def __init__(self, kind, net, layers, rect, half, ref):
        self.kind, self.net, self.layers, self.rect, self.half, self.ref = kind, net, layers, rect, half, ref


def _items(board):
    items = []
    for pad in board.pads():
        layers = ("F.Cu", "B.Cu") if pad.tht else ("F.Cu",)
        items.append(_Item("pad", pad.net, layers, pad.bbox(), 0.0, f"{pad.fp.ref}.{pad.num}"))
    for t in board.tracks:
        r = (min(t.x1, t.x2), min(t.y1, t.y2), max(t.x1, t.x2), max(t.y1, t.y2))
        items.append(_Item("track", t.net, (t.layer,), r, t.width / 2, f"trilha {t.layer} ({t.x1:.2f},{t.y1:.2f})"))
    for v in board.vias:
        items.append(_Item("via", v.net, ("F.Cu", "B.Cu"), (v.x, v.y, v.x, v.y), v.size / 2,
                           f"via ({v.x:.2f},{v.y:.2f})"))
    return items


def _buckets(items, size=2.0):
    grid = defaultdict(list)
    for i, it in enumerate(items):
        x0, y0, x1, y1 = it.rect
        m = it.half + 0.5
        for gx in range(int((x0 - m) // size), int((x1 + m) // size) + 1):
            for gy in range(int((y0 - m) // size), int((y1 + m) // size) + 1):
                grid[(gx, gy)].append(i)
    return grid


def check_board(board):
    rules = board.rules
    items = _items(board)
    grid = _buckets(items)
    errors = []
    seen = set()
    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)

    for cell in grid.values():
        for ii in range(len(cell)):
            for jj in range(ii + 1, len(cell)):
                i, j = cell[ii], cell[jj]
                key = (i, j) if i < j else (j, i)
                if key in seen:
                    continue
                seen.add(key)
                a, b = items[i], items[j]
                if not set(a.layers) & set(b.layers):
                    continue
                if a.kind == "pad" and b.kind == "pad" and a.ref.split(".")[0] == b.ref.split(".")[0]:
                    continue
                gap = _rect_dist(a.rect, b.rect) - a.half - b.half
                if a.net == b.net:
                    if gap <= 1e-6:
                        union(i, j)
                elif gap < rules.clearance - 1e-3:
                    errors.append(f"folga {gap:.3f} mm entre {a.ref} [{a.net}] e {b.ref} [{b.net}]")
    # planos internos (só na placa de 4 camadas) ligam todas as vias / pads THT
    # da mesma net de alimentação; na de 2 camadas a ligação é conferida pelo cobre
    for net in ((board.vdd, board.gnd) if board.layers >= 4 else ()):
        anchor = None
        for i, it in enumerate(items):
            if it.net == net and (it.kind == "via" or (it.kind == "pad" and len(it.layers) == 2)):
                if anchor is None:
                    anchor = i
                else:
                    union(i, anchor)
    comps = defaultdict(set)
    for i, it in enumerate(items):
        if it.kind == "pad" and it.net:
            comps[it.net].add(find(i))
    unconnected = {net: len(c) for net, c in comps.items() if len(c) > 1}
    errors += _floorplan_errors(board, items)
    return errors, unconnected


def _overlaps(a, b, m=0.0):
    return a[0] - m < b[2] and b[0] - m < a[2] and a[1] - m < b[3] and b[1] - m < a[3]


def _floorplan_errors(board, items):
    """Confere, independentemente do placement e do roteador, as restrições do
    floorplan: membros dentro da sua fence/region, ninguém de fora numa fence,
    nada nos keepouts."""
    fp = getattr(board, "floorplan", None)
    if fp is None:
        return []
    errors = []
    gmod = getattr(board, "group_modules", {})
    for f in board.footprints:
        x0, y0, x1, y1 = f.courtyard
        box = (f.x + x0, f.y + y0, f.x + x1, f.y + y1)
        for k in fp.keepouts:
            if k.place and _overlaps(box, k.rect):
                errors.append(f"floorplan: {f.ref} dentro do keepout '{k.name}'")
        if not f.group:
            continue                     # desacopladores e conectores não pertencem a módulo
        mod = gmod.get(f.group, "")
        rule = fp.rule_of(mod) if mod else None
        if rule and rule.type in ("fence", "region"):
            r = rule.rect
            if not (r[0] - 1e-6 <= box[0] and r[1] - 1e-6 <= box[1] and box[2] <= r[2] + 1e-6
                    and box[3] <= r[3] + 1e-6):
                errors.append(f"floorplan: {f.ref} ({mod}) fora da {rule.type} de '{rule.path}'")
        for other in fp.modules.values():
            if other.type == "fence" and other is not rule and _overlaps(box, other.rect) \
                    and not (mod == other.path or mod.startswith(other.path + ".")):
                errors.append(f"floorplan: {f.ref} ({mod or 'topo'}) invade a fence de '{other.path}'")
    for it in items:
        if it.kind == "pad":
            continue
        for k in fp.keepouts:
            if k.route and set(it.layers) & set(k.layers) and _overlaps(it.rect, k.rect, it.half):
                errors.append(f"floorplan: {it.ref} [{it.net}] dentro do keepout de roteamento '{k.name}'")
    return errors
