"""Placement em fileiras (estilo standard-cell) com anelamento simulado.

Cada bloco (instância de subcircuito com componentes) é desenhado conforme o
'layout' do JSON da célula — por exemplo, PMOS em cima e NMOS embaixo, ou
resistores em cima e NPN embaixo. Os blocos são distribuídos em fileiras e o
anelamento minimiza o HPWL (half-perimeter wire length) das nets de sinal.

Quando o projeto tem mais de um módulo Verilog no topo, cada um ganha uma
região retangular própria (floorplan): as regiões são empacotadas na placa e
os blocos só se movem dentro da região do seu módulo. Submódulos dentro de uma
região são mantidos juntos por uma net virtual (só no custo).

As fileiras são tratadas como "trechos": (x inicial, y, capacidade). Sem
floorplan há um trecho por fileira da placa; com floorplan, um por fileira de
cada região.
"""

import math
import random
from dataclasses import dataclass

from .layout import Board, Rules, footprint_from_library, pin_header


@dataclass
class PlaceParams:
    part_gap: float = None       # folga entre componentes dentro do bloco (mm)
    row_gap: float = None        # canal de roteamento entre fileiras de blocos
    cell_gap: float = 1.5        # folga entre blocos na mesma fileira
    margin: float = 4.0          # borda da placa
    io_gap: float = 6.0          # distância entre conectores e a área de lógica
    effort: float = 1.0          # multiplica o número de movimentos do anelamento
    floorplan: bool = True       # uma região retangular por módulo do topo
    module_weight: float = 2.0   # peso da net virtual que agrupa submódulos (0 = desliga)
    module_max_blocks: int = 400 # módulos maiores não ganham net virtual (custo do anelamento)
    seed: int = 1


def _snap(v, g):
    return round(v / g) * g


def place(lib, design, params=None, rules=None):
    params = params or PlaceParams()
    rules = rules or Rules()
    part_gap = params.part_gap if params.part_gap is not None else lib.placement.get("part_gap", 1.0)
    row_gap = params.row_gap if params.row_gap is not None else lib.placement.get("row_gap", 4.5)
    rng = random.Random(params.seed)
    blocks = design.blocks
    n = len(blocks)
    power = {design.vdd, design.gnd}

    layouts = {}
    for b in blocks:
        if b.cell not in layouts:
            layouts[b.cell] = lib.block_layout(b.cell, part_gap)
    width = [layouts[b.cell][1] + params.cell_gap for b in blocks]
    block_h = max(l[2] for l in layouts.values())
    row_pitch = block_h + row_gap

    # --- nets de sinal ------------------------------------------------------
    net_blocks = {}
    for i, b in enumerate(blocks):
        for net in set(b.pins.values()) - power:
            net_blocks.setdefault(net, set()).add(i)

    # --- conectores de E/S --------------------------------------------------
    inputs = [p for p in design.ports if p.direction == "input"]
    outputs = [p for p in design.ports if p.direction != "input"]
    left = [(design.vdd, "VDD"), (design.gnd, "GND")] + [(p.net, p.name) for p in inputs]
    right = [(p.net, p.name) for p in outputs] + [(design.gnd, "GND")]

    dec = lib.meta.get("decoupling", {})
    dec_row = lib.parts.get(dec.get("row", ""))
    dec_w = 0.0
    if dec_row:
        c = lib.footprints[dec_row["footprint"]]["courtyard"]
        dec_w = c[2] - c[0]

    # --- regiões (uma por módulo do topo) e trechos de fileira ------------
    region_of_key = {}
    region = [region_of_key.setdefault(b.module.split(".")[0] if b.module else "", len(region_of_key))
              for b in blocks]
    if not params.floorplan or len(region_of_key) < 2:
        region = [0] * n
        region_names = [""]
    else:
        region_names = sorted(region_of_key, key=region_of_key.get)
    n_reg = len(region_names)
    reg_blocks = [[] for _ in range(n_reg)]
    for v in range(n):
        reg_blocks[region[v]].append(v)
    reg_size = []                       # (n_fileiras, capacidade, largura, altura)
    for bl in reg_blocks:
        tot = sum(width[v] for v in bl)
        nr = max(1, round(math.sqrt(tot / row_pitch)))
        cp = max(tot / nr * 1.08 + params.cell_gap, max(width[v] for v in bl) + params.cell_gap)
        reg_size.append((nr, cp, cp + params.cell_gap + dec_w, nr * row_pitch))

    # empacotamento em prateleiras (regiões mais altas primeiro); o espaço
    # entre regiões é um canal de roteamento como o das fileiras
    reg_xy = [None] * n_reg
    gap = row_gap
    target = max(max(w for _, _, w, _ in reg_size),
                 math.sqrt(sum((w + gap) * h for _, _, w, h in reg_size)) * 1.1)
    sx = sy = shelf_h = 0.0
    for r in sorted(range(n_reg), key=lambda r: (-reg_size[r][3], region_names[r])):
        _, _, w, h = reg_size[r]
        if sx > 0 and sx + w > target:
            sx, sy, shelf_h = 0.0, sy + shelf_h, 0.0
        reg_xy[r] = (sx, sy)
        sx += w + gap
        shelf_h = max(shelf_h, h)
    logic_w = max(reg_xy[r][0] + reg_size[r][2] for r in range(n_reg))
    logic_h = max(reg_xy[r][1] + reg_size[r][3] for r in range(n_reg))

    io_h = max(len(left), len(right)) * 2.54
    x0 = params.margin + 2.54 + params.io_gap
    y0 = params.margin + 2.0 + max(0.0, (io_h - logic_h) / 2)
    left_x = params.margin + 1.27
    right_x = x0 + logic_w + params.io_gap + 1.27

    slots = []                          # (x inicial, y, capacidade, região)
    reg_slots = [[] for _ in range(n_reg)]
    for r in range(n_reg):
        nr, cp, _, _ = reg_size[r]
        for k in range(nr):
            reg_slots[r].append(len(slots))
            slots.append((x0 + reg_xy[r][0], y0 + reg_xy[r][1] + k * row_pitch, cp, r))
    n_rows = len(slots)

    fixed = {}
    for entries, x in ((left, left_x), (right, right_x)):
        for k, (net, _) in enumerate(entries):
            if net not in power:
                fixed.setdefault(net, []).append((x, params.margin + 1.27 + k * 2.54))
    nets = list(set(net_blocks) | set(fixed))
    net_index = {net: k for k, net in enumerate(nets)}
    nets_of_block = [[net_index[nt] for nt in set(b.pins.values()) - power] for b in blocks]
    members = [list(net_blocks.get(net, ())) for net in nets]
    weight = [1.0] * len(nets)
    fixed_box = []
    for net in nets:
        pts = fixed.get(net, [])
        fixed_box.append((min(p[0] for p in pts), max(p[0] for p in pts),
                          min(p[1] for p in pts), max(p[1] for p in pts)) if pts else None)

    # nets virtuais de módulo (u_a.u_b agrupa em u_a.u_b e também em u_a)
    mod_blocks = {}
    for i, b in enumerate(blocks):
        parts = b.module.split(".") if b.module else []
        for k in range(1, len(parts) + 1):
            mod_blocks.setdefault(".".join(parts[:k]), []).append(i)
    if params.module_weight > 0:
        for mod, bl in sorted(mod_blocks.items()):
            if 2 <= len(bl) <= params.module_max_blocks:
                e = len(members)
                members.append(bl)
                weight.append(params.module_weight)
                fixed_box.append(None)
                for i in bl:
                    nets_of_block[i].append(e)

    # --- estado inicial: ordem por conectividade (BFS), preenchendo fileiras
    order, seen = [], set()
    adj = [set() for _ in range(n)]
    for m in members:
        if len(m) < 30:
            for a in m:
                adj[a].update(m)
    for s in range(n):
        if s in seen:
            continue
        queue = [s]
        seen.add(s)
        while queue:
            v = queue.pop(0)
            order.append(v)
            for w in sorted(adj[v]):
                if w not in seen:
                    seen.add(w)
                    queue.append(w)
    order.sort(key=lambda v: blocks[v].module)   # estável: BFS dentro de cada módulo
    rows = [[] for _ in range(n_rows)]
    for r in range(n_reg):
        ks = reg_slots[r]
        i, acc = 0, 0.0
        for v in order:
            if region[v] != r:
                continue
            if acc + width[v] > slots[ks[i]][2] and i < len(ks) - 1:
                i, acc = i + 1, 0.0
            rows[ks[i]].append(v)
            acc += width[v]
        for i in range(1, len(ks), 2):   # serpentina: vizinhos ficam próximos
            rows[ks[i]].reverse()

    px = [0.0] * n
    py = [0.0] * n
    row_of = [0] * n

    def layout_row(k):
        x, y = slots[k][0], slots[k][1]
        for v in rows[k]:
            px[v] = x + width[v] / 2
            py[v] = y
            row_of[v] = k
            x += width[v]

    for k in range(n_rows):
        layout_row(k)

    def hpwl(e):
        fb = fixed_box[e]
        if fb:
            xmin, xmax, ymin, ymax = fb
        else:
            xmin = ymin = math.inf
            xmax = ymax = -math.inf
        for v in members[e]:
            x, y = px[v], py[v]
            if x < xmin: xmin = x
            if x > xmax: xmax = x
            if y < ymin: ymin = y
            if y > ymax: ymax = y
        if xmax < xmin:
            return 0.0
        return ((xmax - xmin) + (ymax - ymin)) * weight[e]

    row_len = [sum(width[v] for v in row) for row in rows]

    def overflow(k):
        return max(0.0, row_len[k] - slots[k][2]) ** 2 * 2.0

    net_cost = [hpwl(e) for e in range(len(members))]
    n_real = len(nets)

    def affected(row_ids):
        es = set()
        for k in row_ids:
            for v in rows[k]:
                es.update(nets_of_block[v])
        return es

    def try_move():
        # os blocos só mudam de lugar dentro da própria região
        a = rng.randrange(n)
        ra = row_of[a]
        mates = reg_blocks[region[a]]
        if rng.random() < 0.5 and len(mates) > 1:
            b = rng.choice(mates)
            rb = row_of[b]
            ia, ib = rows[ra].index(a), rows[rb].index(b)
            rows[ra][ia], rows[rb][ib] = b, a
            return ("swap", ra, ia, rb, ib)
        rb = rng.choice(reg_slots[region[a]])
        ia = rows[ra].index(a)
        rows[ra].pop(ia)
        ib = rng.randrange(len(rows[rb]) + 1)
        rows[rb].insert(ib, a)
        return ("move", ra, ia, rb, ib)

    def undo_move(u):
        kind, ra, ia, rb, ib = u
        if kind == "swap":
            rows[ra][ia], rows[rb][ib] = rows[rb][ib], rows[ra][ia]
        else:
            a = rows[rb].pop(ib)
            rows[ra].insert(ia, a)

    def evaluate(rs):
        es = affected(rs)
        old = sum(net_cost[e] for e in es) + sum(overflow(k) for k in rs)
        for k in rs:
            layout_row(k)
            row_len[k] = sum(width[v] for v in rows[k])
        new_costs = {e: hpwl(e) for e in es}
        new = sum(new_costs.values()) + sum(overflow(k) for k in rs)
        return new - old, new_costs

    if n > 1:
        moves = int(max(2000, 150 * n) * params.effort)
        samples = []
        for _ in range(min(200, moves)):
            u = try_move()
            rs = {u[1], u[3]}
            d, _ = evaluate(rs)
            samples.append(abs(d))
            undo_move(u)
            evaluate(rs)
        temp = (sum(samples) / len(samples) or 1.0) * 2
        steps = 60
        per_step = max(1, moves // steps)
        for _ in range(steps):
            for _ in range(per_step):
                u = try_move()
                rs = {u[1], u[3]}
                d, nc = evaluate(rs)
                if d <= 0 or rng.random() < math.exp(-d / temp):
                    for e, c in nc.items():
                        net_cost[e] = c
                else:
                    undo_move(u)
                    evaluate(rs)
            temp *= 0.9

    # --- geração dos footprints ------------------------------------------
    g = rules.grid
    footprints = []
    counters = {}

    def next_ref(prefix):
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}{counters[prefix]}"

    # referências numeradas por módulo (faixa contínua por módulo) e, dentro
    # dele, na ordem física: fileira e depois x
    for v in sorted(range(n), key=lambda v: (blocks[v].module, row_of[v], px[v])):
        b = blocks[v]
        pos, _, _ = layouts[b.cell]
        left_edge = px[v] - width[v] / 2 + params.cell_gap / 2
        for part in sorted(b.parts, key=lambda p: (pos[p.name][1], pos[p.name][0])):
            dev = lib.parts[part.model]
            part.ref = next_ref(dev.get("ref", "U"))
            fp = footprint_from_library(lib, dev["footprint"], part.ref, part.value)
            dx, dy = pos[part.name]
            fp.x = _snap(left_edge + dx, g)
            fp.y = _snap(py[v] + dy, g)
            fp.group = b.group
            for role, num in dev["pins"].items():
                pad = fp.pad(num)
                pad.net = part.pins[role]
                pad.function = role
            footprints.append(fp)

    def decap(key, x_left, y_center):
        dev = lib.parts[key]
        fp = footprint_from_library(lib, dev["footprint"], next_ref(dev.get("ref", "C")), dev.get("value", key))
        c = fp.courtyard
        fp.x = _snap(x_left - c[0], g)
        fp.y = _snap(y_center - (c[1] + c[3]) / 2, g)
        fp.pad(dev["pins"]["1"]).net = design.vdd
        fp.pad(dev["pins"]["2"]).net = design.gnd
        footprints.append(fp)

    if dec_row:                          # um desacoplamento no fim de cada trecho
        for sx, sy, cp, _ in slots:
            decap(dec["row"], sx + cp + params.cell_gap, sy + block_h / 2)
    if dec.get("bulk"):
        decap(dec["bulk"], left_x - 1.0, params.margin + 1.27 + len(left) * 2.54 + 4.0)

    # conectores (divididos em barras de no máximo 40 pinos)
    jn = 0
    port_label = {}
    for side, entries, x in (("in", left, left_x), ("out", right, right_x)):
        for start in range(0, len(entries), 40):
            chunk = entries[start:start + 40]
            jn += 1
            hdr = pin_header(f"J{jn}", len(chunk), "IN" if side == "in" else "OUT")
            hdr.x = x
            hdr.y = params.margin + 1.27 + start * 2.54
            for pad, (net, label) in zip(hdr.pads, chunk):
                pad.net = net
                pad.function = label
            port_label[hdr.ref] = [lbl for _, lbl in chunk]
            footprints.append(hdr)

    bw = right_x + 1.27 + params.margin
    bh = max(y0 + logic_h - row_gap + params.margin,
             params.margin + 1.27 + max(len(left) + 4, len(right)) * 2.54 + params.margin + 4.0)
    board = Board(_snap(bw + 0.5, 1.0), _snap(bh + 0.5, 1.0), footprints, design.vdd, design.gnd, rules)
    for fp in footprints:
        if fp.group:
            board.groups.setdefault(fp.group, []).append(fp.uuid)
    board.port_labels = port_label
    board.place_stats = {"rows": n_rows, "regions": n_reg if n_reg > 1 else 0,
                         "hpwl_mm": round(sum(net_cost[:n_real]), 1), "blocks": n}
    return board
