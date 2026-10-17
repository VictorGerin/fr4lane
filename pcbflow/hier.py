"""Fluxo hierárquico: macros implementados à parte e copiados (bottom-up), com
a posição deles decidida de cima (top-down: floorplan ou empacotamento).

Um macro é um TIPO de módulo do Verilog (--macro adder ou "macros" no
floorplan). As instâncias desse tipo com a mesma estrutura (mesmas portas,
ligadas do mesmo jeito; o sizing por fan-out pode diferenciar uma instância)
compartilham um MOLDE:

  1. o molde é posicionado e roteado sozinho, num retângulo com margem; as
     nets que saem dele ganham um PINO na borda (o ponto da borda mais perto
     dos terminais da net, F.Cu nas laterais e B.Cu em cima/embaixo);
  2. macros dentro de macros entram no molde de fora como peças prontas (é
     a mesma montagem, recursiva); moldes do mesmo nível rodam em paralelo,
     um processo cada;
  3. no topo, cada instância recebe uma cópia do seu molde (componentes,
     trilhas e vias, com as nets e as instâncias lógicas renomeadas), num
     retângulo reservado com um canal livre em volta; o resto ("cola") é
     posicionado normalmente, e o roteador de cima liga os pinos dos macros e
     os pads da cola. O cobre dos macros é obstáculo para ele (até para a
     própria net, que entra pelo pino); o espaço livre dentro deles, não.

A simulação de componentes, a verificação e o DRC continuam sobre a placa
inteira. Só para placas de 4 camadas (VDD/GND nos planos internos).
"""

import dataclasses
import math
import os
import re
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

from . import place as placemod
from . import progress
from .floorplan import Floorplan, FloorplanError, Keepout
from .layout import Board, Footprint, Pad, Track, Via
from .netlist import Design
from .route import FREE, Router

RING = 1.5        # canal livre em volta de cada macro (acesso aos pinos), mm
MARGIN = 1.5      # borda interna do macro, entre a lógica e os pinos
LAYERS = ("F.Cu", "B.Cu")


class HierError(Exception):
    pass


@dataclass
class Template:
    """Um macro pronto, em coordenadas próprias (origem no canto superior
    esquerdo) e com as nets e instâncias lógicas da instância 'path'."""
    type: str
    path: str
    w: float
    h: float
    footprints: list
    tracks: list
    vias: list
    pins: list            # (net, x, y, camada) na borda
    cells: int
    unrouted: list
    seconds: float


def _up(v, g):
    return math.ceil(v / g - 1e-9) * g


# ------------------------------------------------------------------ análise
def analyze(design, types):
    """Instâncias de macro, a que molde cada uma pertence e como mapear o molde
    em cada instância (nets e instâncias lógicas)."""
    known = set(design.modules.values())
    missing = sorted(set(types) - known)
    if missing:
        raise HierError(f"tipo(s) de macro {', '.join(missing)} não existe(m) no projeto "
                        f"(tipos: {', '.join(sorted(known)) or 'nenhum: o projeto não tem submódulos'})")
    paths = sorted(p for p, t in design.modules.items() if t in types)
    cells = {p: [] for p in paths}
    for inst in design.instances:
        m = design.inst_module.get(inst, "")
        for p in paths:
            if m == p or m.startswith(p + "."):
                cells[p].append(inst)
    paths = [p for p in paths if cells[p]]              # módulo sem portas: nada a fazer
    parent = {}
    for p in paths:
        anc = [q for q in paths if p.startswith(q + ".")]
        parent[p] = max(anc, key=len) if anc else None
    depth = {p: 0 for p in paths}
    for p in paths:
        q = parent[p]
        while q:
            depth[p] += 1
            q = parent[q]

    power = {design.vdd, design.gnd}
    users = defaultdict(set)
    for inst, conns in design.conns.items():
        for net in conns.values():
            users[net].add(inst)
    port_nets = {p.net for p in design.ports}

    info = {}
    for p in paths:
        cs = set(cells[p])
        nets = {n for i in cs for n in design.conns[i].values()} - power
        boundary = {n for n in nets if (users[n] - cs) or n in port_nets}
        # nome da porta relativo à instância: tira do nome do Yosys os segmentos do
        # caminho dela (que vêm decorados: _flatten_u0._u0._abc...); o resto é
        # igual em todas as instâncias com a mesma estrutura
        depth_p = len(p.split("."))
        rel = {}
        for i in cells[p]:
            segs = design.instances[i][1].split(".")
            rel[".".join(segs[depth_p:]) if len(segs) > depth_p else f"?{i}"] = i
        canon, items = {}, []
        for r in sorted(rel):
            i = rel[r]
            for pin in sorted(design.conns[i]):
                n = design.conns[i][pin]
                c = n if n in power else canon.setdefault(n, len(canon))
                items.append((r, design.instances[i][0], pin, c))
        nets_in_order = sorted(canon, key=canon.get)
        flags = tuple(n in boundary for n in nets_in_order)
        unique = any(r.startswith("?") for r in rel)        # sem nome relativo: não dá para copiar
        key = ("só", p) if unique else (design.modules[p], tuple(items), flags)
        info[p] = {"type": design.modules[p], "cells": cells[p], "boundary": sorted(boundary),
                   "rel": rel, "canon": nets_in_order, "key": key, "parent": parent[p], "depth": depth[p]}
    rep = {}
    by_key = {}
    for p in paths:
        rep[p] = by_key.setdefault(info[p]["key"], p)
    return paths, info, rep


def _maps(info, src, dst):
    """Nets e instâncias lógicas do molde (instância src) para a instância dst."""
    a, b = info[src], info[dst]
    netmap = dict(zip(a["canon"], b["canon"]))
    cellmap = {a["rel"][r]: b["rel"][r] for r in a["rel"]}
    return netmap, cellmap


# --------------------------------------------------------------- geometria
def _pack(sizes, x0, y0, width, g):
    """Prateleiras: cada macro (w, h) com o canal RING em volta, da esquerda para
    a direita e de cima para baixo. Devolve [(ox, oy, retângulo com o canal)]."""
    out = []
    x, y, shelf = x0, y0, 0.0
    for w, h in sizes:
        if x > x0 and x + w + 2 * RING > x0 + width + 1e-6:
            x, y, shelf = x0, y + shelf, 0.0
        ox, oy = _up(x + RING, g), _up(y + RING, g)
        rect = (ox - RING, oy - RING, ox + w + RING, oy + h + RING)
        out.append((ox, oy, rect))
        x = rect[2]
        shelf = max(shelf, rect[3] - y)
    return out


def _copy(board, tpl, ox, oy, netmap, cellmap):
    """Cópia do molde na placa, deslocada para (ox, oy) e renomeada."""
    def net(n):
        if n in netmap:
            return netmap[n]
        # nets internas de uma porta levam o nome da instância lógica: U12.X1.b1
        head, dot, tail = n.partition(".")
        if dot and head in cellmap:
            return f"{cellmap[head]}.{tail}"
        return n

    for f in tpl.footprints:
        nf = Footprint(f.ref, f.value, f.lib_name, f.x + ox, f.y + oy, courtyard=f.courtyard,
                       silk=list(f.silk), tht=f.tht, group=cellmap.get(f.group, f.group) if f.group else "")
        for p in f.pads:
            nf.pads.append(Pad(p.num, p.rx, p.ry, p.w, p.h, p.shape, tht=p.tht, drill=p.drill,
                               net=net(p.net) if p.net else "", function=p.function, fp=nf, macro=True))
        board.footprints.append(nf)
    for t in tpl.tracks:
        board.tracks.append(Track(t.x1 + ox, t.y1 + oy, t.x2 + ox, t.y2 + oy, t.layer, net(t.net), t.width))
    for v in tpl.vias:
        board.vias.append(Via(v.x + ox, v.y + oy, net(v.net), v.size, v.drill))
    if not hasattr(board, "macro_rects"):
        board.macro_rects = []
    board.macro_rects.append((ox, oy, ox + tpl.w, oy + tpl.h))
    return [(net(n), x + ox, y + oy, layer) for n, x, y, layer in tpl.pins]


def _choose_pins(rt, nets):
    """Um pino por net na borda do macro: o lado mais perto dos terminais da net
    e, nele, o ponto livre mais perto; pinos a 1 mm um do outro."""
    nx, ny, g = rt.nx, rt.ny, rt.g
    used = defaultdict(set)
    pins = []
    for net in nets:
        nid = rt.net_id[net]
        pts = [rt.coords(n)[1:] for t in rt.terminals.get(nid, []) for n in t]
        if not pts:
            raise HierError(f"a net {net} sai do macro mas não tem terminal dentro dele")
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        sides = sorted([(cx, "L"), (nx - 1 - cx, "R"), (cy, "T"), (ny - 1 - cy, "B")])
        found = None
        for _, side in sides:
            along, n_along = (cy, ny) if side in "LR" else (cx, nx)
            for k in sorted(range(2, n_along - 2), key=lambda k: (abs(k - along), k)):
                if k in used[side]:
                    continue
                if side == "L":
                    layer, ix, iy, jx, jy = 0, 0, k, 1, k
                elif side == "R":
                    layer, ix, iy, jx, jy = 0, nx - 1, k, nx - 2, k
                elif side == "T":
                    layer, ix, iy, jx, jy = 1, k, 0, k, 1
                else:
                    layer, ix, iy, jx, jy = 1, k, ny - 1, k, ny - 2
                if rt.static[rt.node(layer, ix, iy)] != FREE:
                    continue
                if rt.static[rt.node(layer, jx, jy)] not in (FREE, nid):
                    continue
                found = (side, k, layer, ix, iy)
                break
            if found:
                break
        if not found:
            raise HierError(f"não há lugar na borda do macro para o pino da net {net}")
        side, k, layer, ix, iy = found
        used[side].update((k - 1, k, k + 1))
        rt.add_pin(net, ix, iy, layer)
        pins.append((net, ix * g, iy * g, layer))
    return pins


# ------------------------------------------------------------ um molde
def build_template(job):
    """Posiciona e roteia um molde (roda num processo auxiliar se houver outros
    do mesmo nível). job: dicionário montado em place_hier."""
    t0 = time.time()
    lib, params, rules = job["lib"], job["params"], job["rules"]
    g = rules.grid
    bare = dataclasses.replace(params, bare=True, margin=MARGIN)
    blocks = job["blocks"]
    sub = Design(job["path"], [], blocks, job["vdd"], job["gnd"])
    children = job["children"]                      # [(caminho, Template, netmap, cellmap)]

    row_pitch = placemod._measure(lib, sub, bare, rules).geo.row_pitch if blocks else 0.0
    glue_w = sum(placemod._measure(lib, sub, bare, rules).width) if blocks else 0.0
    area = sum((t.w + 2 * RING) * (t.h + 2 * RING) for _, t, _, _ in children) + glue_w * row_pitch
    width = max([t.w + 2 * RING for _, t, _, _ in children] + [math.sqrt(area) * 1.15, 10.0])
    origin = _up(MARGIN, g)
    spots = _pack([(t.w, t.h) for _, t, _, _ in children], origin, origin, width, g)
    extra = defaultdict(list)
    for (_, t, netmap, _), (ox, oy, _) in zip(children, spots):
        for n, x, y, _layer in t.pins:
            extra[netmap.get(n, n)].append((ox + x, oy + y))

    if blocks:
        fp = Floorplan(f"macro {job['type']}",
                       keepouts=[Keepout(f"macro {c}", rect, True, False, LAYERS)
                                 for (c, _, _, _), (_, _, rect) in zip(children, spots)])
        board = placemod.place(lib, sub, bare, rules, fp, extra_fixed=dict(extra))
    else:
        board = Board(0.0, 0.0, [], job["vdd"], job["gnd"], rules)
        board.layers = 4
    right = max([r[2] for _, _, r in spots] + [0.0]) + MARGIN
    bottom = max([r[3] for _, _, r in spots] + [0.0]) + MARGIN
    board.width, board.height = _up(max(board.width, right), g), _up(max(board.height, bottom), g)
    board.keepouts, board.floorplan = [], None
    board.pins = []
    for (_, t, netmap, cellmap), (ox, oy, _) in zip(children, spots):
        board.pins += _copy(board, t, ox, oy, netmap, cellmap)

    rt = Router(board, log=lambda m: None, edge=False, label=f"macro {job['type']}: ")
    pins = _choose_pins(rt, job["boundary"])
    failed_power = rt.fanout_power()
    unrouted = rt.route_signals(job["route_iter"]) + [f"(alim) {p}" for p in failed_power]
    return Template(job["type"], job["path"], board.width, board.height, board.footprints, board.tracks,
                    board.vias, pins, job["n_cells"], unrouted, time.time() - t0)


# ------------------------------------------------------------------- topo
def place_hier(lib, design, params, rules, fplan, types, route_iter, log=print):
    """Placement hierárquico: devolve a placa com os macros já roteados por dentro
    (o roteamento de cima liga os pinos deles) e um resumo para o log."""
    if params.layers != 4:
        raise HierError("macros só em placas de 4 camadas (VDD/GND nos planos internos)")
    paths, info, rep = analyze(design, types)
    if not paths:
        raise HierError(f"nenhuma instância de {', '.join(types)} com portas no projeto")
    g = rules.grid
    blocks_of = defaultdict(list)
    for b in design.blocks:
        blocks_of[b.group].append(b)
    children = defaultdict(list)
    for p in paths:
        children[info[p]["parent"]].append(p)

    def glue_cells(p):
        inner = {i for c in children[p] for i in info[c]["cells"]}
        own = info[p]["cells"] if p else list(design.instances)
        return [i for i in own if i not in inner]

    # moldes, do mais fundo para o mais raso; os do mesmo nível em paralelo
    reps = sorted(set(rep.values()), key=lambda p: (-info[p]["depth"], p))
    tpls = {}
    with progress.Progress(f"macros: {len(reps)} molde(s)", total=len(reps)) as pg:
        for d in sorted({info[p]["depth"] for p in reps}, reverse=True):
            jobs = []
            for p in (r for r in reps if info[r]["depth"] == d):
                kids = []
                for c in children[p]:
                    netmap, cellmap = _maps(info, rep[c], c)
                    kids.append((c, tpls[rep[c]], netmap, cellmap))
                jobs.append({"lib": lib, "params": params, "rules": rules, "route_iter": route_iter,
                             "path": p, "type": info[p]["type"], "vdd": design.vdd, "gnd": design.gnd,
                             "blocks": [b for i in glue_cells(p) for b in blocks_of[i]],
                             "children": kids, "boundary": info[p]["boundary"],
                             "n_cells": len(info[p]["cells"])})
            workers = min(len(jobs), os.cpu_count() or 1)
            if workers > 1:
                with ProcessPoolExecutor(max_workers=workers, initializer=progress.silence) as ex:
                    futs = [ex.submit(build_template, j) for j in jobs]
                    for f in as_completed(futs):
                        t = f.result()
                        tpls[t.path] = t
                        pg.update(len(tpls), f"{t.type} pronto")
            else:
                for j in jobs:
                    pg.update(len(tpls), f"{j['type']}")
                    t = build_template(j)
                    tpls[t.path] = t
                    pg.update(len(tpls), f"{t.type} pronto")

    # topo: onde fica cada macro
    top = children[None]
    glue = [b for i in glue_cells(None) for b in blocks_of[i]]
    glue_design = Design(design.top, design.ports, glue, design.vdd, design.gnd)
    geo = placemod._measure(lib, glue_design, params, rules).geo
    spot = {}
    if fplan is None:
        sizes = [(tpls[rep[m]].w, tpls[rep[m]].h) for m in top]
        area = sum((w + 2 * RING) * (h + 2 * RING) for w, h in sizes) + \
            sum(placemod._measure(lib, glue_design, params, rules).width) * geo.row_pitch
        width = max([w + 2 * RING for w, _ in sizes] + [math.sqrt(area) * 1.15])
        for m, s in zip(top, _pack(sizes, geo.x0, geo.y_top, width, g)):
            spot[m] = s
    else:
        inside = defaultdict(list)
        loose = []
        for m in top:
            t = tpls[rep[m]]
            r = fplan.modules.get(m)
            if r is not None and r.type in ("fence", "region"):
                x0, y0, x1, y1 = r.rect
                if x1 - x0 < t.w + 2 * RING - 1e-6 or y1 - y0 < t.h + 2 * RING - 1e-6:
                    raise FloorplanError(f"{fplan.source}: a área de '{m}' ({x1 - x0:g} x {y1 - y0:g} mm) não "
                                         f"comporta o macro {t.type} ({t.w + 2 * RING:g} x {t.h + 2 * RING:g} mm "
                                         "com o canal de acesso aos pinos)")
                ox, oy = _up(x0 + RING, g), _up(y0 + RING, g)
                spot[m] = (ox, oy, r.rect)
                continue
            anc = [q for q in fplan.modules if m.startswith(q + ".")
                   and fplan.modules[q].type in ("fence", "region")]
            if anc:
                inside[max(anc, key=len)].append(m)
            else:
                loose.append(m)
        # macros sem área (nem do módulo que os contém): numa faixa abaixo de tudo
        # o que o floorplan declara, para não cair em cima de nenhuma área
        if loose:
            areas = [r.rect for r in fplan.modules.values() if r.type in ("fence", "region")]
            areas += [k.rect for k in fplan.keepouts]
            y0 = max([geo.y_top] + [r[3] for r in areas])
            sizes = [(tpls[rep[m]].w, tpls[rep[m]].h) for m in loose]
            width = max([w + 2 * RING for w, _ in sizes] +
                        [math.sqrt(sum((w + 2 * RING) * (h + 2 * RING) for w, h in sizes)) * 1.15])
            for m, s in zip(loose, _pack(sizes, geo.x0, y0, width, g)):
                spot[m] = s
        for q, ms in inside.items():
            x0, y0, x1, y1 = fplan.modules[q].rect
            sizes = [(tpls[rep[m]].w, tpls[rep[m]].h) for m in ms]
            packed = _pack(sizes, x0, y0, x1 - x0, g)
            need_w = max(r[2] for _, _, r in packed) - x0
            need_h = max(r[3] for _, _, r in packed) - y0
            if need_w > x1 - x0 + 1e-6 or need_h > y1 - y0 + 1e-6:
                raise FloorplanError(f"{fplan.source}: os {len(ms)} macro(s) de dentro de '{q}' "
                                     f"({', '.join(sorted({tpls[rep[m]].type for m in ms}))}) não cabem na área "
                                     f"dela ({x1 - x0:g} x {y1 - y0:g} mm): empacotados na largura dela, precisam "
                                     f"de {need_w:g} x {need_h:g} mm (mais o espaço dos blocos soltos do módulo)")
            for m, s in zip(ms, packed):
                spot[m] = s

    # floorplan para os blocos soltos: as áreas que ainda têm blocos e, como
    # keepout de posicionamento, os macros (com o canal) e as áreas só de macros
    syn = Floorplan(fplan.source if fplan else "(macros)", board=fplan.board if fplan else None)
    glue_mods = {b.module for b in glue}
    macro_paths = set(paths)
    for path, r in (fplan.modules.items() if fplan else ()):
        if any(path == p or path.startswith(p + ".") for p in macro_paths):
            continue
        if any(m == path or m.startswith(path + ".") for m in glue_mods):
            syn.modules[path] = r
        elif r.type == "fence":
            syn.keepouts.append(Keepout(f"área de {path}", r.rect, True, False, LAYERS))
    syn.keepouts += list(fplan.keepouts) if fplan else []
    for m in top:
        syn.keepouts.append(Keepout(f"macro {m}", spot[m][2], True, False, LAYERS))
    extra = defaultdict(list)
    for m in top:
        netmap, _ = _maps(info, rep[m], m)
        ox, oy, _ = spot[m]
        for n, x, y, _layer in tpls[rep[m]].pins:
            extra[netmap.get(n, n)].append((ox + x, oy + y))

    board = placemod.place(lib, glue_design, params, rules, syn, extra_fixed=dict(extra))
    board.pins = []
    for m in top:
        netmap, cellmap = _maps(info, rep[m], m)
        ox, oy, _ = spot[m]
        board.pins += _copy(board, tpls[rep[m]], ox, oy, netmap, cellmap)
    board.keepouts = list(fplan.keepouts) if fplan else []
    board.floorplan = fplan
    board.groups = {}
    for f in board.footprints:
        if f.group:
            board.groups.setdefault(f.group, []).append(f.uuid)
    _renumber(board, design.inst_module)

    copies = defaultdict(int)
    for p in paths:
        copies[rep[p]] += 1
    summary = [(t.type, t.path, t.w, t.h, t.cells, copies[t.path], t.unrouted, t.seconds)
               for t in sorted(tpls.values(), key=lambda t: (info[t.path]["depth"], t.path), reverse=True)]
    return board, summary


def _renumber(board, inst_module):
    """Referências únicas na placa montada (cada cópia trouxe as do seu molde):
    por prefixo, na ordem módulo, y, x. Os conectores (J) ficam como estão."""
    by_prefix = defaultdict(list)
    for f in board.footprints:
        if f.lib_name.startswith("Connector_"):
            continue
        m = re.match(r"[A-Za-z]+", f.ref)
        mod = inst_module.get(f.group, "") if f.group else "~"
        by_prefix[m.group(0) if m else "U"].append(((mod, round(f.y, 3), round(f.x, 3)), f))
    for prefix, items in by_prefix.items():
        items.sort(key=lambda t: t[0])
        for k, (_, f) in enumerate(items, 1):
            f.ref = f"{prefix}{k}"
