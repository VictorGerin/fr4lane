"""Placement em fileiras (estilo standard-cell) com anelamento simulado.

Cada bloco (instância de subcircuito com componentes) é desenhado conforme o
'layout' do JSON da célula — por exemplo, PMOS em cima e NMOS embaixo, ou
resistores em cima e NPN embaixo. Os blocos são distribuídos em fileiras e o
anelamento minimiza o HPWL (half-perimeter wire length) das nets de sinal.

As fileiras são tratadas como "trechos": (x inicial, y, capacidade, dono).
Cada bloco tem a lista de trechos onde pode ficar, e o anelamento só o move
entre eles. Os trechos vêm de um de dois construtores:

  automático   cada módulo instanciado no topo ganha uma região retangular
               própria; as regiões são dimensionadas e empacotadas na placa.
  declarado    (--floorplan) as fileiras de uma grade global são cortadas
               pelas áreas do arquivo: fence e region só aceitam seus membros
               (a fence também barra os de fora), keepouts de posicionamento
               removem o trecho, e guide vira custo no anelamento.

Nos dois casos as fileiras caem numa grade global (passo = bloco + canal), o
que a placa de 2 camadas usa: sem planos internos, a alimentação vira uma
grade de cobre fixa desenhada aqui — um trilho de VDD acima e um de GND
abaixo de cada fileira (F.Cu), ligados por vias a troncos verticais (B.Cu)
dos dois lados da lógica, e estes aos pinos de alimentação dos conectores.
O roteador liga cada pad de alimentação ao trilho mais próximo.
"""

import math
import random
from dataclasses import dataclass
from types import SimpleNamespace

from .floorplan import FloorplanError, contains, overlap
from .layout import Board, Rules, Track, Via, footprint_from_library, pin_header


@dataclass
class PlaceParams:
    part_gap: float = None       # folga entre componentes dentro do bloco (mm)
    row_gap: float = None        # canal de roteamento entre fileiras de blocos
    cell_gap: float = 1.5        # folga entre blocos na mesma fileira
    margin: float = 4.0          # borda da placa
    io_gap: float = 6.0          # distância entre conectores e a área de lógica
    effort: float = 1.0          # multiplica o número de movimentos do anelamento
    floorplan: bool = True       # automático: uma região retangular por módulo do topo
    layers: int = 4              # 4: VDD/GND em planos internos; 2: trilhos de alimentação
    rail_extra: float = 2.5      # 2 camadas: canal extra entre fileiras para os trilhos (mm)
    rail_width: float = 0.8      # 2 camadas: largura dos trilhos horizontais
    trunk_width: float = 1.0     # 2 camadas: largura dos troncos verticais
    module_weight: float = 2.0   # peso da net virtual que agrupa submódulos (0 = desliga)
    module_max_blocks: int = 400 # módulos maiores não ganham net virtual (custo do anelamento)
    guide_weight: float = 1.0    # 'guide': peso da distância de cada bloco até a área
    density: float = 0.8         # ocupação-alvo das fileiras fora das fences/regions (1 = compacto,
                                 # encostado à esquerda); elas espalham o módulo pela área toda
    density_weight: float = 1.0  # força com que o anelamento respeita a ocupação-alvo
    seed: int = 1


def _snap(v, g):
    return round(v / g) * g


class _Geo:
    """Medidas comuns aos dois construtores de trechos."""

    def __init__(self, params, rules, two, row_gap, block_h, dec_w, n_left, n_right):
        g = rules.grid
        self.params, self.two = params, two
        self.block_h, self.dec_w = block_h, dec_w
        self.row_gap = row_gap
        self.row_pitch = block_h + row_gap
        self.trunk_band = 4.0 if two else 0.0      # faixa dos troncos de alimentação de cada lado
        self.x0 = _snap(params.margin + 2.54 + params.io_gap + self.trunk_band, g)  # borda esq. da lógica
        # da borda direita da lógica até a borda da placa
        self.reserve_r = self.trunk_band + params.io_gap + 2.54 + params.margin
        self.y_top = _snap(params.margin + 2.0 + (0.5 if two else 0.0), g)
        self.min_h = params.margin + 1.27 + max(n_left + 4, n_right) * 2.54 + params.margin + 4.0
        self.io_h = max(n_left, n_right) * 2.54
        self.margin, self.cell_gap = params.margin, params.cell_gap

    def as_dict(self):
        """Medidas da grade para o placement.json (o fpedit refaz as fileiras com elas)."""
        keys = ("two", "block_h", "dec_w", "row_gap", "row_pitch", "x0", "reserve_r", "y_top",
                "min_h", "margin", "cell_gap")
        return {k: getattr(self, k) for k in keys}


def _measure(lib, design, params, rules):
    """Medidas que só dependem da síntese, da família e do número de camadas:
    largura de cada bloco, altura das fileiras, conectores e a grade (_Geo)."""
    two = params.layers == 2
    part_gap = lib.placement.get("part_gap", 1.0)
    if two:   # na placa de 2 camadas as ligações aos trilhos passam entre os componentes
        part_gap = lib.placement.get("part_gap_2layer", part_gap)
    if params.part_gap is not None:
        part_gap = params.part_gap
    row_gap = params.row_gap if params.row_gap is not None else lib.placement.get("row_gap", 4.5)
    if two and params.row_gap is None:
        row_gap += params.rail_extra
    blocks = design.blocks

    layouts = {}
    for b in blocks:
        if b.cell not in layouts:
            layouts[b.cell] = lib.block_layout(b.cell, part_gap)
    width = [layouts[b.cell][1] + params.cell_gap for b in blocks]
    block_h = max(l[2] for l in layouts.values())

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

    geo = _Geo(params, rules, two, row_gap, block_h, dec_w, len(left), len(right))
    return SimpleNamespace(two=two, part_gap=part_gap, layouts=layouts, width=width, block_h=block_h,
                           left=left, right=right, geo=geo, dec=dec, dec_row=dec_row)


def _editor_info(blocks, width, geo):
    """Para o fpedit: grade e largura de fileira que cada módulo ocupa."""
    mod_w = {}
    for v, b in enumerate(blocks):
        mod_w[b.module] = mod_w.get(b.module, 0.0) + width[v]
    return {"geo": geo.as_dict(), "module_width": mod_w, "min_width": min(width, default=0.0)}


def measure(lib, design, params=None, rules=None):
    """As mesmas medidas do placement, sem posicionar nada (make pcb-stat): o
    que o fpedit precisa e o tamanho que a placa teria sem floorplan."""
    params = params or PlaceParams()
    m = _measure(lib, design, params, rules or Rules())
    info = _editor_info(design.blocks, m.width, m.geo)
    fm = _auto_slots(design.blocks, m.width, m.geo)
    info["board"] = [fm["W"], fm["H"]]
    return info


def place(lib, design, params=None, rules=None, floorplan=None):
    params = params or PlaceParams()
    rules = rules or Rules()
    g = rules.grid
    m = _measure(lib, design, params, rules)
    two, layouts, width, block_h = m.two, m.layouts, m.width, m.block_h
    left, right, geo, dec, dec_row = m.left, m.right, m.geo, m.dec, m.dec_row
    rng = random.Random(params.seed)
    blocks = design.blocks
    n = len(blocks)
    power = {design.vdd, design.gnd}

    # --- nets de sinal ------------------------------------------------------
    net_blocks = {}
    for i, b in enumerate(blocks):
        for net in set(b.pins.values()) - power:
            net_blocks.setdefault(net, set()).add(i)

    if floorplan is None:
        fm = _auto_slots(blocks, width, geo)
    else:
        fm = _declared_slots(blocks, width, geo, floorplan)
    slots, allowed, rows = fm["slots"], fm["allowed"], fm["rows"]
    W, H, y0, n_global, lx1 = fm["W"], fm["H"], fm["y0"], fm["n_global"], fm["lx1"]
    x0 = geo.x0
    n_rows = len(slots)
    left_x = params.margin + 1.27
    right_x = W - params.margin - 1.27

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

    def virtual_net(bl, w, box=None):
        e = len(members)
        members.append(bl)
        weight.append(w)
        fixed_box.append(box)
        for i in bl:
            nets_of_block[i].append(e)

    # nets virtuais de módulo (u_a.u_b agrupa em u_a.u_b e também em u_a)
    mod_blocks = {}
    for i, b in enumerate(blocks):
        parts = b.module.split(".") if b.module else []
        for k in range(1, len(parts) + 1):
            mod_blocks.setdefault(".".join(parts[:k]), []).append(i)
    if params.module_weight > 0:
        for mod, bl in sorted(mod_blocks.items()):
            if 2 <= len(bl) <= params.module_max_blocks:
                virtual_net(bl, params.module_weight)
    # guide: cada bloco do módulo paga a distância até a área desejada, como
    # se tivesse um fio até ela (px = centro do bloco, py = topo da fileira)
    for rule, bl in fm.get("guides", []):
        rx0, ry0, rx1, ry1 = rule.rect
        box = (rx0, rx1, ry0 - block_h / 2, max(ry0, ry1 - block_h) - block_h / 2)
        for v in bl:
            virtual_net([v], params.guide_weight, box)

    px = [0.0] * n
    py = [0.0] * n
    row_of = [0] * n

    target, spread = fm["target"], fm["spread"]

    def layout_row(k):
        # com ocupação-alvo < 1, a sobra da fileira é repartida entre os blocos
        # (meio vão em cada ponta), em múltiplos da grade
        x, y = slots[k][0], slots[k][1]
        gap = 0.0
        if spread[k] and rows[k]:
            free = slots[k][2] - sum(width[v] for v in rows[k])
            if free > 0:
                gap = math.floor(free / len(rows[k]) / g) * g
                x += math.floor(gap / 2 / g) * g
        for v in rows[k]:
            px[v] = x + width[v] / 2
            py[v] = y
            row_of[v] = k
            x += width[v] + gap

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

    dw = params.density_weight

    def overflow(k):
        x = max(0.0, row_len[k] - slots[k][2])
        # acima da ocupação-alvo: custo mais brando, que espalha sem forçar
        t = max(0.0, row_len[k] - target[k]) if target[k] < slots[k][2] - 1e-6 else 0.0
        return x * x * 2.0 + x * 10.0 + (t * t * 0.5 + t * 2.0) * dw

    net_cost = [hpwl(e) for e in range(len(members))]
    n_real = len(nets)

    def affected(row_ids):
        es = set()
        for k in row_ids:
            for v in rows[k]:
                es.update(nets_of_block[v])
        return es

    # blocos com a mesma lista de trechos permitidos podem trocar de lugar
    classes = {}
    for v in range(n):
        classes.setdefault(id(allowed[v]), []).append(v)
    mates = [classes[id(allowed[v])] for v in range(n)]

    def try_move():
        a = rng.randrange(n)
        ra = row_of[a]
        if rng.random() < 0.5 and len(mates[a]) > 1:
            b = rng.choice(mates[a])
            rb = row_of[b]
            ia, ib = rows[ra].index(a), rows[rb].index(b)
            rows[ra][ia], rows[rb][ib] = b, a
            return ("swap", ra, ia, rb, ib)
        rb = rng.choice(allowed[a])
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
    owner = fm["owner"]
    # legalização: o anelamento só penaliza o excesso; aqui os blocos que
    # sobram numa fileira cheia vão para o trecho permitido mais próximo com espaço
    def move(v, src, dst):
        rows[src].remove(v)
        xs = [px[u] for u in rows[dst]]      # entra perto do x atual
        rows[dst].insert(sum(1 for x in xs if x < px[v]), v)
        for r in (src, dst):
            layout_row(r)
            row_len[r] = sum(width[u] for u in rows[r])

    def fits(v, j):
        return row_len[j] + width[v] <= slots[j][2] + 1e-6

    def evict_guest(tag, skip):
        """Abre espaço numa region tirando um bloco livre (intruso) de uma das
        fileiras dela para um trecho livre."""
        for j in range(n_rows):
            if j == skip or slots[j][3] != tag:
                continue
            for u in rows[j]:
                if owner[u] is None:
                    for j2 in allowed[u]:
                        if slots[j2][3] == "free" and fits(u, j2):
                            move(u, j, j2)
                            return True
        return False

    for k in sorted(range(n_rows), key=lambda k: row_len[k] - slots[k][2], reverse=True):
        while row_len[k] - slots[k][2] > 0.01:
            best = None
            for v in rows[k]:
                # quem não é dono do trecho (bloco livre numa region) sai primeiro
                guest = owner[v] is None and slots[k][3] != "free"
                for j in allowed[v]:
                    if j != k and fits(v, j):
                        d = abs(slots[j][1] - py[v]) + abs(slots[j][0] + row_len[j] - px[v])
                        d -= 1e6 if guest else 0.0
                        if best is None or d < best[0]:
                            best = (d, v, j)
            if best is not None:
                move(best[1], k, best[2])
            elif not evict_guest(slots[k][3], k):
                break
    net_cost = [hpwl(e) for e in range(len(members))]
    over = [(k, row_len[k] - slots[k][2]) for k in range(n_rows) if row_len[k] - slots[k][2] > 0.01]
    if over and floorplan is not None:
        where = sorted({slots[k][3] for k, _ in over})
        raise FloorplanError(
            f"os blocos não couberam nas fileiras de {', '.join(w if w != 'free' else '(sem área)' for w in where)} "
            f"(excesso de até {max(o for _, o in over):.1f} mm): aumente essas áreas ou a placa")

    # --- geração dos footprints ------------------------------------------
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

    board = Board(W, H, footprints, design.vdd, design.gnd, rules)
    board.layers = params.layers
    board.floorplan = floorplan
    board.keepouts = floorplan.keepouts if floorplan else []
    if two:
        hdr_y = lambda k: params.margin + 1.27 + k * 2.54
        _power_grid(board, params, rules, x0, lx1, y0, n_global, geo.row_pitch, block_h,
                    left_x, right_x, hdr_y(0), hdr_y(1), hdr_y(len(right) - 1), board.keepouts)
    for fp in footprints:
        if fp.group:
            board.groups.setdefault(fp.group, []).append(fp.uuid)
    board.port_labels = port_label
    board.place_stats = {"rows": n_rows, "regions": fm.get("n_regions", 0),
                         "hpwl_mm": round(sum(net_cost[:n_real]), 1), "blocks": n,
                         "usage": fm.get("usage", []), "grid": fm.get("grid"),
                         "logic_x": (x0, lx1)}
    board.place_stats["editor"] = _editor_info(blocks, width, geo)
    return board


# ------------------------------------------------------- trechos: automático
def _fill(order, ks, room, width, rows, used):
    """Preenche os trechos ks na ordem dada, cada um até room[k]; devolve o que não coube."""
    i = 0
    rest = []
    for v in order:
        while i < len(ks) and used.get(ks[i], 0.0) + width[v] > room[ks[i]] + 1e-6:
            i += 1
        if i == len(ks):
            rest.append(v)
            continue
        rows[ks[i]].append(v)
        used[ks[i]] = used.get(ks[i], 0.0) + width[v]
    return rest


def _fill_area(order, ks, slots, target, width, rows, used):
    """Distribuição inicial de uma área: as fileiras até a ocupação-alvo e o que
    sobrar até a capacidade, em serpentina (vizinhos ficam próximos); devolve
    o que não coube. O anelamento decide depois onde o módulo fica."""
    cap = {k: slots[k][2] for k in ks}
    rest = _fill(order, ks, target, width, rows, used)
    rest = _fill(rest, ks, cap, width, rows, used)
    for j in range(1, len(ks), 2):
        rows[ks[j]].reverse()
    return rest


def _bfs_order(blocks):
    """Blocos em ordem de conectividade (BFS), agrupados por módulo."""
    n = len(blocks)
    by_net = {}
    for i, b in enumerate(blocks):
        for net in set(b.pins.values()):
            by_net.setdefault(net, []).append(i)
    adj = [set() for _ in range(n)]
    for m in by_net.values():
        if len(m) < 30:
            for a in m:
                adj[a].update(m)
    order, seen = [], set()
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
    return order


def _auto_slots(blocks, width, geo):
    params = geo.params
    n = len(blocks)
    region_of_key = {}
    region = [region_of_key.setdefault(b.module.split(".")[0] if b.module else "", len(region_of_key))
              for b in blocks]
    if not params.floorplan or len(region_of_key) < 2:
        region = [0] * n
        n_reg = 1
    else:
        n_reg = len(region_of_key)
    names = sorted(region_of_key, key=region_of_key.get) if n_reg > 1 else [""]
    reg_blocks = [[] for _ in range(n_reg)]
    for v in range(n):
        reg_blocks[region[v]].append(v)
    reg_size = []                       # (n_fileiras, capacidade, largura, altura)
    for bl in reg_blocks:
        tot = sum(width[v] for v in bl)
        nr = max(1, round(math.sqrt(tot / geo.row_pitch)))
        cp = max(tot / nr * 1.08 + params.cell_gap, max(width[v] for v in bl) + params.cell_gap)
        reg_size.append((nr, cp, cp + params.cell_gap + geo.dec_w, nr * geo.row_pitch))

    # empacotamento em prateleiras (regiões mais altas primeiro); o espaço
    # entre regiões é um canal de roteamento como o das fileiras
    reg_xy = [None] * n_reg
    gap = geo.row_gap
    target = max(max(w for _, _, w, _ in reg_size),
                 math.sqrt(sum((w + gap) * h for _, _, w, h in reg_size)) * 1.1)
    sx = sy = shelf_h = 0.0
    for r in sorted(range(n_reg), key=lambda r: (-reg_size[r][3], names[r])):
        _, _, w, h = reg_size[r]
        if sx > 0 and sx + w > target:
            sx, sy, shelf_h = 0.0, sy + shelf_h, 0.0
        reg_xy[r] = (sx, sy)
        sx += w + gap
        shelf_h = max(shelf_h, h)
    logic_w = max(reg_xy[r][0] + reg_size[r][2] for r in range(n_reg))
    logic_h = max(reg_xy[r][1] + reg_size[r][3] for r in range(n_reg))
    y0 = _snap(geo.y_top + max(0.0, (geo.io_h - logic_h) / 2), 0.5)

    slots, reg_slots = [], [[] for _ in range(n_reg)]
    for r in range(n_reg):
        nr, cp, _, _ = reg_size[r]
        for k in range(nr):
            reg_slots[r].append(len(slots))
            slots.append((geo.x0 + reg_xy[r][0], y0 + reg_xy[r][1] + k * geo.row_pitch, cp, names[r]))
    allowed = [reg_slots[region[v]] for v in range(n)]
    rows = [[] for _ in slots]
    order = _bfs_order(blocks)
    # sem floorplan as regiões já saem justas (8% de folga): a meta é a capacidade,
    # e a densidade só reparte essa folga dentro de cada fileira
    target = [s[2] for s in slots]
    used = {}
    for r in range(n_reg):
        ks = reg_slots[r]
        rest = _fill_area([v for v in order if region[v] == r], ks, slots, target, width, rows, used)
        for v in rest:                      # não deve acontecer (8% de folga); vai pro último
            rows[ks[-1]].append(v)
    W_raw = geo.x0 + logic_w + geo.reserve_r
    H_raw = max(y0 + logic_h - geo.row_gap + params.margin, geo.min_h)
    return {"slots": slots, "allowed": allowed, "rows": rows, "owner": [names[region[v]] for v in range(n)],
            "target": target, "spread": [params.density < 1.0] * len(slots),
            "W": _snap(W_raw + 0.5, 1.0), "H": _snap(H_raw + 0.5, 1.0), "y0": y0,
            "n_global": max(1, round(logic_h / geo.row_pitch)), "lx1": geo.x0 + logic_w,
            "n_regions": n_reg if n_reg > 1 else 0}


# -------------------------------------------------------- trechos: declarado
def declared_rows(geo, fplan, W, H, min_width):
    """Fileiras de uma placa W x H cortadas pelas áreas do floorplan: devolve
    (trechos, n_fileiras, x final da lógica). Cada trecho é (x, y, capacidade,
    dono), com dono = caminho da fence/region ou "free". geo é um _Geo ou
    qualquer objeto com os mesmos atributos (o fpedit usa o do placement.json)."""
    hard = {r.path: r for r in fplan.modules.values() if r.type in ("fence", "region")}
    lx0, lx1 = geo.x0, W - geo.reserve_r
    ly1 = H - geo.margin - (1.5 if geo.two else 0.0)
    for r in hard.values():
        if r.rect[0] < lx0 - 1e-6 or r.rect[2] > lx1 + 1e-6:
            raise FloorplanError(
                f"{fplan.source}: a área de '{r.path}' sai da região de lógica, que vai de "
                f"x = {lx0:g} a {lx1:g} mm (fora dela ficam os conectores"
                + (" e os troncos de alimentação)" if geo.two else ")"))
    slots = []
    k = 0
    while geo.y_top + k * geo.row_pitch + geo.block_h <= ly1:
        y = geo.y_top + k * geo.row_pitch
        band = (lx0, y, lx1, y + geo.block_h)
        # pontos de corte: bordas x das áreas que tocam a faixa da fileira
        rects = [(r.rect, ("mod", r)) for r in hard.values() if overlap(r.rect, band)]
        rects += [(ko.rect, ("ko", ko)) for ko in fplan.keepouts if ko.place and overlap(ko.rect, band)]
        cuts = sorted({lx0, lx1} | {min(max(x, lx0), lx1) for rc, _ in rects for x in (rc[0], rc[2])})
        pieces = []
        for a, b in zip(cuts, cuts[1:]):
            if b - a < 1e-6:
                continue
            cell = (a, y, b, y + geo.block_h)
            tag = "free"
            inside = None
            for rc, (kind, obj) in rects:
                if not overlap(rc, cell):
                    continue
                if kind == "ko":
                    tag = None
                    break
                if contains(rc, cell):
                    if inside is None or len(obj.path) > len(inside.path):
                        inside = obj
                elif obj.type == "fence":
                    tag = None              # fileira cortada pela borda de uma fence
                    break
            if tag is not None and inside is not None:
                tag = inside.path
            if pieces and pieces[-1][2] == tag and abs(pieces[-1][1] - a) < 1e-6:
                pieces[-1][1] = b
            else:
                pieces.append([a, b, tag])
        for a, b, tag in pieces:
            if tag is None:
                continue
            # folga nas pontas: o arredondamento para a grade não encosta o
            # bloco (ou o desacoplador) na borda de uma área ou keepout
            a, b = a + 0.5, b - 0.5
            cap = (b - a) - geo.cell_gap - geo.dec_w
            if cap >= min_width - 1e-6:
                slots.append((_snap(a, 0.5), y, cap, tag))
        k += 1
    return slots, k, lx1


def owner_of(fplan, module_path):
    """Dono de um bloco no floorplan declarado: o caminho da fence/region que
    vale para o módulo dele, ou None (bloco livre)."""
    r = fplan.rule_of(module_path) if module_path else None
    return r.path if r and r.type in ("fence", "region") else None


def declared_capacity(fplan, slots, need):
    """Fileira oferecida por dono e o que falta: (have, áreas curtas, livres curtos).
    need: dono -> largura somada dos blocos (None = blocos livres)."""
    hard = {r.path: r for r in fplan.modules.values() if r.type in ("fence", "region")}
    have = {}
    for s in slots:
        have[s[3]] = have.get(s[3], 0.0) + s[2]
    short = [path for path in hard if need.get(path, 0.0) > have.get(path, 0.0) * 0.9]
    # os blocos livres usam os trechos livres e o que sobra das regions
    spare = have.get("free", 0.0) + sum(max(0.0, have.get(p, 0.0) * 0.95 - need.get(p, 0.0))
                                        for p, r in hard.items() if r.type == "region")
    return have, short, need.get(None, 0.0) > spare * 0.95


def declared_layout(geo, fplan, need, total_width, min_width):
    """Tamanho da placa e trechos do floorplan declarado. Com 'board' a placa é
    fixa; sem ele, começa pela estimativa sem restrições e cresce a altura até
    os blocos livres caberem, sempre contendo as áreas declaradas."""
    if fplan.board:
        W, H = fplan.board
        if H < geo.min_h:
            raise FloorplanError(f"{fplan.source}: placa com {H:g} mm de altura não comporta os "
                                 f"conectores ({geo.min_h:.0f} mm)")
        slots, n_global, lx1 = declared_rows(geo, fplan, W, H, min_width)
        have, short, free_short = declared_capacity(fplan, slots, need)
    else:
        nr = max(1, round(math.sqrt(total_width / geo.row_pitch)))
        logic_w = total_width / nr * 1.08 + 2 * geo.cell_gap + geo.dec_w
        W = max(geo.x0 + logic_w + geo.reserve_r,
                max((r.rect[2] for r in fplan.modules.values()), default=0) + geo.reserve_r)
        H = max(geo.y_top + nr * geo.row_pitch + geo.margin + (1.5 if geo.two else 0.0), geo.min_h,
                max((r.rect[3] for r in fplan.modules.values()), default=0) + geo.margin)
        W, H = _snap(W + 0.5, 1.0), _snap(H + 0.5, 1.0)
        for _ in range(400):
            slots, n_global, lx1 = declared_rows(geo, fplan, W, H, min_width)
            have, short, free_short = declared_capacity(fplan, slots, need)
            if short or not free_short:
                break
            H += geo.row_pitch / 2
        H = _snap(H + 0.5, 1.0)
    return {"slots": slots, "n_global": n_global, "lx1": lx1, "W": W, "H": H, "have": have,
            "short": short, "free_short": free_short}


def declared_problems(geo, fplan, lay, need):
    """Mensagens para as áreas que não comportam seus módulos (vazia se tudo cabe)."""
    slots, have, W, H = lay["slots"], lay["have"], lay["W"], lay["H"]
    out = []
    for path in lay["short"]:
        r = fplan.modules[path]
        x0, y0, x1, y1 = r.rect
        rows_in = len({s[1] for s in slots if s[3] == path})
        bands = [(geo.y_top + k * geo.row_pitch, geo.y_top + k * geo.row_pitch + geo.block_h)
                 for k in range(lay["n_global"] + 2)]
        near = [f"{a:.1f}–{b:.1f}" for a, b in bands if b > y0 - geo.row_pitch and a < y1 + geo.row_pitch]
        out.append(
            f"{fplan.source}: '{path}' ({r.type}) não cabe na área {x1 - x0:g} x {y1 - y0:g} mm: "
            f"precisa de ~{need.get(path, 0.0) / 0.9:.0f} mm de fileira e a área oferece {have.get(path, 0):.0f} mm "
            f"em {rows_in} fileira(s). Uma fileira só conta se a faixa inteira estiver dentro da área; "
            f"perto dela as fileiras ocupam y = {', '.join(near)} mm. Aumente a largura ou a altura")
    if lay["free_short"]:
        out.append(
            f"{fplan.source}: os módulos sem área declarada precisam de ~{need.get(None, 0) / 0.95:.0f} mm de "
            f"fileira e a placa de {W:g} x {H:g} mm oferece {have.get('free', 0):.0f} mm livres: "
            "aumente a placa ou remova 'board' para o tamanho automático")
    return out


def declared_density(geo, fplan, slots, need, default):
    """Ocupação-alvo das fileiras por dono de trecho (fence/region ou "free"):
    (densidade, ocupação real, meta em mm de cada trecho). Uma fence/region sem
    "density" usa a ocupação real: espalha o módulo por igual pela área toda,
    e o tamanho da área é o controle. Os trechos livres usam o padrão do fluxo.
    A meta nunca fica abaixo da ocupação real, senão o módulo não caberia."""
    have = {}
    for s in slots:
        have[s[3]] = have.get(s[3], 0.0) + s[2]
    dens, util = {}, {}
    for tag, h in have.items():
        r = fplan.modules.get(tag) if tag != "free" else None
        util[tag] = min(1.0, need.get(None if tag == "free" else tag, 0.0) / h) if h > 0 else 0.0
        if r is None:
            dens[tag] = default
        else:
            dens[tag] = r.density if r.density is not None else util[tag]
    target = {k: s[2] * min(1.0, max(dens[s[3]], util[s[3]])) for k, s in enumerate(slots)}
    return dens, util, target


def _declared_slots(blocks, width, geo, fplan):
    n = len(blocks)
    modules = {b.module for b in blocks if b.module}
    for path in fplan.modules:
        if not any(m == path or m.startswith(path + ".") for m in modules):
            raise FloorplanError(f"{fplan.source}: módulo '{path}' não existe no projeto "
                                 f"(módulos: {', '.join(sorted({m.split('.')[0] for m in modules})) or 'nenhum'})")
    rule = [fplan.rule_of(b.module) if b.module else None for b in blocks]
    hard = {r.path: r for r in fplan.modules.values() if r.type in ("fence", "region")}
    owner = [owner_of(fplan, b.module) for b in blocks]
    need = {}
    for v in range(n):
        need[owner[v]] = need.get(owner[v], 0.0) + width[v]

    lay = declared_layout(geo, fplan, need, sum(width), min(width))
    problems = declared_problems(geo, fplan, lay, need)
    if problems:
        raise FloorplanError(problems[0])
    slots, n_global, lx1, W, H, have = (lay[k] for k in ("slots", "n_global", "lx1", "W", "H", "have"))

    # trechos permitidos de cada bloco
    by_tag = {}
    for k, s in enumerate(slots):
        by_tag.setdefault(s[3], []).append(k)
    shared = by_tag.get("free", []) + [k for p, r in hard.items() if r.type == "region" for k in by_tag.get(p, [])]
    shared.sort(key=lambda k: (slots[k][1], slots[k][0]))
    allowed = [by_tag.get(owner[v], []) if owner[v] else shared for v in range(n)]

    dens, util, target = declared_density(geo, fplan, slots, need, geo.params.density)
    spread = [dens[s[3]] < 1.0 for s in slots]

    rows = [[] for _ in slots]
    used = {}
    order = _bfs_order(blocks)
    for path in hard:
        ks = by_tag.get(path, [])
        rest = _fill_area([v for v in order if owner[v] == path], ks, slots, target, width, rows, used)
        for v in rest:
            rows[ks[-1]].append(v)
    rest = _fill_area([v for v in order if owner[v] is None], shared, slots, target, width, rows, used)
    for v in rest:                           # o anelamento acerta o excesso
        k = max(shared, key=lambda k: slots[k][2] - used.get(k, 0.0))
        rows[k].append(v)
        used[k] = used.get(k, 0.0) + width[v]

    guides = []
    for r in fplan.modules.values():
        if r.type == "guide":
            bl = [v for v in range(n) if rule[v] is r]
            if bl:
                guides.append((r, bl))
    grid = (geo.y_top, geo.row_pitch, geo.block_h, n_global)
    usage = [(p, r.type, need.get(p, 0.0), have.get(p, 0.0)) for p, r in hard.items()]
    usage.append(("(sem área)", "", need.get(None, 0.0), have.get("free", 0.0)))
    return {"slots": slots, "allowed": allowed, "rows": rows, "owner": owner, "target": target, "spread": spread,
            "W": W, "H": H, "y0": geo.y_top,
            "n_global": n_global, "lx1": lx1, "guides": guides, "n_regions": len(hard), "usage": usage,
            "grid": grid}


# ------------------------------------------------- alimentação de 2 camadas
def _cut(a, b, holes):
    """Intervalo [a, b] menos os intervalos 'holes'."""
    out = [(a, b)]
    for h0, h1 in holes:
        nxt = []
        for s0, s1 in out:
            if h1 <= s0 or h0 >= s1:
                nxt.append((s0, s1))
                continue
            if h0 > s0:
                nxt.append((s0, h0))
            if h1 < s1:
                nxt.append((h1, s1))
        out = nxt
    return out


def _power_grid(board, params, rules, xl, xr, y0, n_rows, row_pitch, block_h,
                left_x, right_x, y_vdd_in, y_gnd_in, y_gnd_out, keepouts=()):
    """Grade de alimentação fixa da placa de 2 camadas (veja o docstring do módulo).
    Trilhos que cruzam um keepout de roteamento são interrompidos; só ficam os
    pedaços ligados a algum tronco."""
    g = rules.grid
    rw, tw = params.rail_width, params.trunk_width
    off = _snap(rw / 2 + rules.clearance + 0.6, g)       # trilho -> borda da fileira
    xs = {"gnd": (_snap(xl - 3.5, g), _snap(xr + 3.5, g)),   # troncos: GND por fora,
          "vdd": (_snap(xl - 1.5, g), _snap(xr + 1.5, g))}   # VDD por dentro
    nets = {"gnd": board.gnd, "vdd": board.vdd}
    rails = {"vdd": [], "gnd": []}
    for m in range(n_rows):
        y = y0 + m * row_pitch
        rails["vdd"].append(_snap(y - off, g))
        rails["gnd"].append(_snap(y + block_h + off, g))
    route_ko = [k for k in keepouts if k.route]

    def holes(layer, y, half):
        m = rules.clearance + half
        return [(k.rect[0] - m, k.rect[2] + m) for k in route_ko
                if layer in k.layers and k.rect[1] - m < y < k.rect[3] + m]

    # ligações dos pinos de alimentação dos conectores aos troncos: (x do pino, y, lado)
    stubs = {"vdd": [(left_x, y_vdd_in, 0)], "gnd": [(left_x, y_gnd_in, 0), (right_x, y_gnd_out, 1)]}
    for key in ("vdd", "gnd"):
        net = nets[key]
        a, b = xs[key]
        span = [[], []]                       # extensão vertical de cada tronco
        for y in rails[key]:
            for s0, s1 in _cut(a, b, holes("F.Cu", y, rw / 2)):
                ends = [side for side, x in ((0, a), (1, b)) if abs((s0 if side == 0 else s1) - x) < 1e-6]
                if not ends:
                    continue                  # pedaço isolado entre dois keepouts
                board.tracks.append(Track(s0, y, s1, y, "F.Cu", net, rw))
                for side in ends:
                    board.vias.append(Via(xs[key][side], y, net, rules.via_size, rules.via_drill))
                    span[side].append(y)
        for hx, hy, side in stubs[key]:
            tx = xs[key][side]
            board.tracks.append(Track(hx, hy, tx, hy, "F.Cu", net, rw))
            board.vias.append(Via(tx, hy, net, rules.via_size, rules.via_drill))
            span[side].append(hy)
        for side, x in enumerate(xs[key]):
            if not span[side]:
                continue
            y_a, y_b = min(span[side]), max(span[side])
            for k in route_ko:
                m = rules.clearance + tw / 2
                if "B.Cu" in k.layers and k.rect[0] - m < x < k.rect[2] + m and k.rect[1] - m < y_b \
                        and y_a < k.rect[3] + m:
                    raise FloorplanError(f"keepout '{k.name}' cruza o tronco de {net} em x = {x:g} mm "
                                         "(B.Cu); mova o keepout ou tire 'B.Cu' das camadas dele")
            board.tracks.append(Track(x, y_a, x, y_b, "B.Cu", net, tw))
