"""Roteador em grade para 2 camadas de sinal (F.Cu/B.Cu).

Estratégia:
  1. Alimentação, placa de 4 camadas: cada pad SMD de VDD/GND ganha um
     "fanout" curto até uma via que desce para o plano interno correspondente
     (In1.Cu=GND, In2.Cu=VDD); pads com furo já tocam os planos.
     Placa de 2 camadas: o placement já desenhou a grade de alimentação
     (trilhos e troncos, tratados aqui como cobre fixo); cada pad de VDD/GND
     vira uma ligação "pad -> trilho" negociada junto com os sinais.
  2. Sinais: roteamento negociado (PathFinder). Todas as nets são roteadas
     permitindo conflito; o custo dos nós disputados cresce a cada iteração
     até que ninguém compartilhe recurso. F.Cu prefere trilhas horizontais e
     B.Cu verticais.

A grade só usa movimentos ortogonais. Com grade <= menor dimensão de pad,
verificar a folga nos nós da grade garante a folga ao longo das trilhas.
"""

import heapq
import math

from .layout import Track, Via
from .progress import Progress

FREE = -1
BLOCK = -2
LAYERS = ("F.Cu", "B.Cu")


def _dist_point_rect(px, py, r):
    x0, y0, x1, y1 = r
    dx = max(x0 - px, 0.0, px - x1)
    dy = max(y0 - py, 0.0, py - y1)
    return math.hypot(dx, dy)


class Router:
    def __init__(self, board, log=print):
        self.b = board
        self.r = board.rules
        self.log = log
        g = self.r.grid
        self.g = g
        self.nx = int(board.width / g) + 1
        self.ny = int(board.height / g) + 1
        self.nxy = self.nx * self.ny
        self.n = 2 * self.nxy
        self.nets = board.nets()
        self.net_id = {name: i for i, name in enumerate(self.nets)}
        self.power = {self.net_id[n] for n in (board.vdd, board.gnd) if n in self.net_id}
        self.static = [FREE] * self.n
        self.via_static = [FREE] * self.nxy
        self.terminals = {}            # net -> [set(nós) por pad]
        self.power_pads = []           # 4 camadas: pads SMD que precisam de fanout
        self.planes = getattr(board, "layers", 4) >= 4
        self.rail = {}                 # net -> nós do cobre fixo (grade de alimentação)
        self.stubs = []                # 2 camadas: (pad, net, nós do pad) a ligar ao trilho
        self._build_static()

    # ------------------------------------------------------------ utilitários
    def node(self, layer, ix, iy):
        return layer * self.nxy + iy * self.nx + ix

    def coords(self, node):
        layer, p = divmod(node, self.nxy)
        iy, ix = divmod(p, self.nx)
        return layer, ix, iy

    def _claim(self, arr, idx, net):
        cur = arr[idx]
        if cur == FREE:
            arr[idx] = net
        elif cur != net and cur != BLOCK:
            arr[idx] = BLOCK

    def _points_near(self, rect, radius):
        g = self.g
        x0, y0, x1, y1 = rect
        ix0 = max(0, int(math.floor((x0 - radius) / g)))
        ix1 = min(self.nx - 1, int(math.ceil((x1 + radius) / g)))
        iy0 = max(0, int(math.floor((y0 - radius) / g)))
        iy1 = min(self.ny - 1, int(math.ceil((y1 + radius) / g)))
        for iy in range(iy0, iy1 + 1):
            for ix in range(ix0, ix1 + 1):
                d = _dist_point_rect(ix * g, iy * g, rect)
                if d < radius - 1e-6:
                    yield ix, iy, d

    # ----------------------------------------------------- obstáculos fixos
    def _build_static(self):
        r, g = self.r, self.g
        track_r = r.clearance + r.track_width / 2
        via_r = r.clearance + r.via_size / 2
        edge_t = r.edge_clearance + r.track_width / 2
        edge_v = r.edge_clearance + r.via_size / 2
        for iy in range(self.ny):
            for ix in range(self.nx):
                x, y = ix * g, iy * g
                d = min(x, y, self.b.width - x, self.b.height - y)
                if d < edge_t:
                    self.static[self.node(0, ix, iy)] = BLOCK
                    self.static[self.node(1, ix, iy)] = BLOCK
                if d < edge_v:
                    self.via_static[iy * self.nx + ix] = BLOCK
        self._fixed_copper()
        self._keepouts()
        for pad in self.b.pads():
            if not pad.net:
                continue
            net = self.net_id[pad.net]
            rect = pad.bbox()
            layers = (0, 1) if pad.tht else (0,)
            term = set()
            for ix, iy, d in self._points_near(rect, track_r):
                # chegada só onde há cobre: no canto do retângulo envolvente de um
                # pad oval/redondo (os conectores ficam fora da grade) a trilha
                # terminaria no vazio
                inside = d <= 1e-9 and pad.dist(ix * g, iy * g) <= 1e-9
                for layer in layers:
                    self._claim(self.static, self.node(layer, ix, iy), net)
                    if inside:
                        term.add(self.node(layer, ix, iy))
            for ix, iy, d in self._points_near(rect, via_r):
                self._claim(self.via_static, iy * self.nx + ix, net)
            if not term:
                raise RuntimeError(f"pad {pad.fp.ref}.{pad.num} não contém nenhum ponto da grade "
                                   f"(grade {g} mm maior que o pad?)")
            if net in self.power:
                if not self.planes:
                    self.stubs.append((pad, net, term))
                elif not pad.tht:
                    self.power_pads.append((pad, net, term))
            else:
                self.terminals.setdefault(net, []).append(term)

    def _fixed_copper(self):
        """Trilhas e vias que já existem na placa (a grade de alimentação da placa
        de 2 camadas) viram obstáculo para as outras nets e alvo para a própria."""
        r = self.r
        for t in self.b.tracks:
            net = self.net_id[t.net]
            layer = LAYERS.index(t.layer)
            rect = (min(t.x1, t.x2), min(t.y1, t.y2), max(t.x1, t.x2), max(t.y1, t.y2))
            nodes = self.rail.setdefault(net, set())
            for ix, iy, d in self._points_near(rect, t.width / 2 + r.clearance + r.track_width / 2):
                self._claim(self.static, self.node(layer, ix, iy), net)
                if d <= t.width / 2 + 1e-9:
                    nodes.add(self.node(layer, ix, iy))
            for ix, iy, d in self._points_near(rect, t.width / 2 + r.clearance + r.via_size / 2):
                self._claim(self.via_static, iy * self.nx + ix, net)
        for v in self.b.vias:
            net = self.net_id[v.net]
            rect = (v.x, v.y, v.x, v.y)
            nodes = self.rail.setdefault(net, set())
            for ix, iy, d in self._points_near(rect, v.size / 2 + r.clearance + r.track_width / 2):
                for layer in (0, 1):
                    self._claim(self.static, self.node(layer, ix, iy), net)
                    if d <= v.size / 2 + 1e-9:
                        nodes.add(self.node(layer, ix, iy))
            for ix, iy, d in self._points_near(rect, v.size + r.clearance):
                self._claim(self.via_static, iy * self.nx + ix, net)

    def _keepouts(self):
        """Keepouts de roteamento do floorplan: nenhuma trilha nas camadas dadas
        e nenhuma via (a via atravessa as duas camadas)."""
        r = self.r
        for k in getattr(self.b, "keepouts", []):
            if not k.route:
                continue
            for ix, iy, _ in self._points_near(k.rect, r.clearance + r.track_width / 2):
                for layer, name in enumerate(LAYERS):
                    i = self.node(layer, ix, iy)
                    if name in k.layers and self.static[i] == FREE:
                        self.static[i] = BLOCK
            for ix, iy, _ in self._points_near(k.rect, r.clearance + r.via_size / 2):
                self.via_static[iy * self.nx + ix] = BLOCK

    def _halo(self, p):
        iy, ix = divmod(p, self.nx)
        out = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            jx, jy = ix + dx, iy + dy
            if 0 <= jx < self.nx and 0 <= jy < self.ny:
                out.append(jy * self.nx + jx)
        return out

    def _via_static_ok(self, p, net):
        if self.via_static[p] not in (FREE, net):
            return False
        for layer in (0, 1):
            if self.static[layer * self.nxy + p] not in (FREE, net):
                return False
        for q in self._halo(p):
            for layer in (0, 1):
                if self.static[layer * self.nxy + q] not in (FREE, net, BLOCK):
                    return False
        return True

    # ---------------------------------------------------- fanout de energia
    def fanout_power(self):
        vias_at = {}                # ponto -> net
        failed = []
        for pad, net, term in self.power_pads:
            start = [n for n in term if n < self.nxy]
            prev = {n: None for n in start}
            frontier = list(start)
            found = None
            for depth in range(14):
                nxt = []
                for n in frontier:
                    in_pad = _dist_point_rect((n % self.nx) * self.g, (n // self.nx) * self.g,
                                              pad.bbox()) < self.r.via_size / 2 + 0.05
                    if vias_at.get(n) == net or (not in_pad and n not in vias_at
                                                 and self._via_static_ok(n, net)):
                        found = n
                        break
                    iy, ix = divmod(n, self.nx)
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        jx, jy = ix + dx, iy + dy
                        if not (0 <= jx < self.nx and 0 <= jy < self.ny):
                            continue
                        m = jy * self.nx + jx
                        if m in prev or self.static[m] not in (FREE, net):
                            continue
                        prev[m] = n
                        nxt.append(m)
                if found is not None:
                    break
                frontier = nxt
            if found is None:
                failed.append(f"{pad.fp.ref}.{pad.num} ({self.nets[net]})")
                continue
            path = [found]
            while prev[path[-1]] is not None:
                path.append(prev[path[-1]])
            for n in path:
                self.static[n] = net
            self._emit_path(list(reversed(path)), self.nets[net])
            if vias_at.get(found) != net:
                vias_at[found] = net
                iy, ix = divmod(found, self.nx)
                self.b.vias.append(Via(ix * self.g, iy * self.g, self.nets[net],
                                       self.r.via_size, self.r.via_drill))
                for layer in (0, 1):
                    self.static[layer * self.nxy + found] = net
                    for q in self._halo(found):
                        i = layer * self.nxy + q
                        if self.static[i] == FREE:
                            self.static[i] = net
                        elif self.static[i] != net:
                            self.static[i] = BLOCK
                for q in self._halo(found):
                    self._claim(self.via_static, q, net)
        return failed

    # ----------------------------------------------------- roteamento sinais
    def route_signals(self, max_iter=40):
        # cada "job" é uma net de sinal (chave = id da net) ou, na placa de 2
        # camadas, a ligação de um pad de alimentação ao trilho (chave = ("pw", i))
        self.jobs = {n: (n, t) for n, t in self.terminals.items() if len(t) > 1}
        self.rail_target = {}
        for net, nodes in self.rail.items():
            if net in self.power and nodes:
                ps = [self.coords(nd) for nd in nodes]
                self.rail_target[net] = (dict.fromkeys(nodes, 0),
                                         (min(p[1] for p in ps), max(p[1] for p in ps),
                                          min(p[2] for p in ps), max(p[2] for p in ps)))
        for i, (pad, net, term) in enumerate(self.stubs):
            if net in self.rail_target:
                self.jobs[("pw", i)] = (net, [term, None])
        nets = list(self.jobs)

        def bbox_size(n):
            if isinstance(n, tuple):
                return -1                    # ligações de alimentação primeiro
            xs, ys = [], []
            for t in self.terminals[n]:
                _, ix, iy = self.coords(next(iter(t)))
                xs.append(ix)
                ys.append(iy)
            return (max(xs) - min(xs)) + (max(ys) - min(ys))

        nets.sort(key=bbox_size)
        self.occ = [0] * self.n
        self.hist = [0.0] * self.n
        self.usage = {n: set() for n in nets}
        self.paths = {n: [] for n in nets}
        self.ok = set()
        pres = 0.5
        todo = list(nets)
        conflicted = set()
        prev = ""
        for it in range(max_iter):
            failed = []
            # a 1ª iteração roteia todas as nets; as seguintes, só as em conflito.
            # As nets vão da menor para a maior: o progresso pesa cada uma pelo
            # tamanho (contar nets subestimaria o tempo das últimas)
            w = [bbox_size(net) + 4 for net in todo]
            total, acc = sum(w), 0
            with Progress(f"roteamento: iteração {it + 1} (máx. {max_iter})", total=total,
                          show_count=False) as pg:
                for k, net in enumerate(todo):
                    self._rip(net)
                    if not self._route_net(net, pres):
                        failed.append(net)
                    acc += w[k]
                    pg.update(acc, f"{k + 1}/{len(todo)} nets" + (f" · {prev}" if prev else ""))
            over = [i for i in range(self.n) if self.occ[i] > 1]
            for i in over:
                self.hist[i] += 0.4
            over_set = set(over)
            conflicted = {n for n in nets if self.usage[n] & over_set}
            self.log(f"  iteração {it + 1:2d}: nós em conflito={len(over):5d}  "
                     f"nets em conflito={len(conflicted):4d}  falhas={len(failed)}")
            if not over and not failed:
                break
            prev = f"anterior: {len(conflicted)} nets em conflito"
            todo = sorted(conflicted | set(failed), key=bbox_size)
            pres *= 1.6
        # nets que continuam em conflito são descartadas (ficam no ratsnest)
        dropped = set(n for n in nets if n not in self.ok)
        pg = Progress("roteamento: descartando nets que seguem em conflito", tick=True)
        with pg:
            self._drop_conflicts(nets, dropped, bbox_size, pg)
        for key in nets:
            for path in self.paths[key]:
                self._emit_path(path, self.nets[self.jobs[key][0]])
        return sorted(self._job_name(k) for k in dropped)

    def _drop_conflicts(self, nets, dropped, bbox_size, pg):
        while True:
            over = [i for i in range(self.n) if self.occ[i] > 1]
            pg.update(info=f"{len(over)} nós em conflito, {len(dropped)} nets descartadas")
            if not over:
                break
            score = {}
            over_set = set(over)
            for n in nets:
                if n not in dropped:
                    c = len(self.usage[n] & over_set)
                    if c:
                        score[n] = c
            worst = max(score, key=lambda n: (score[n], bbox_size(n)))
            self._rip(worst)
            self.paths[worst] = []
            dropped.add(worst)

    def _job_name(self, key):
        if isinstance(key, tuple):
            pad, net, _ = self.stubs[key[1]]
            return f"(alim) {pad.fp.ref}.{pad.num} ({self.nets[net]})"
        return self.nets[key]

    def _rip(self, net):
        for i in self.usage[net]:
            self.occ[i] -= 1
        self.usage[net] = set()
        self.paths[net] = []
        self.ok.discard(net)

    def _route_net(self, key, pres):
        net, terms = self.jobs[key]
        if terms[1] is None:                 # pad de alimentação -> trilho
            target, box = self.rail_target[net]
            if not terms[0].isdisjoint(target):
                self.ok.add(key)
                return True
            path = self._astar(net, terms[0], target, box, pres)
            if path is None:
                return False
            self.usage[key] = self._footprint_of(path)
            for i in self.usage[key]:
                self.occ[i] += 1
            self.paths[key] = [path]
            self.ok.add(key)
            return True
        tree = set(terms[0])
        remaining = list(range(1, len(terms)))
        used = set()
        paths = []
        while remaining:
            remaining = [k for k in remaining if not (terms[k] & tree)]
            if not remaining:
                break
            target = {}
            xs, ys = [], []
            for k in remaining:
                for nd in terms[k]:
                    target[nd] = k
                    _, ix, iy = self.coords(nd)
                    xs.append(ix)
                    ys.append(iy)
            box = (min(xs), max(xs), min(ys), max(ys))
            path = self._astar(net, tree, target, box, pres)
            if path is None:
                for i in used:
                    self.occ[i] -= 1
                return False
            paths.append(path)
            tree.update(path)
            new = self._footprint_of(path)
            for i in new - used:
                self.occ[i] += 1
            used |= new
        self.usage[key] = used
        self.paths[key] = paths
        self.ok.add(key)
        return True

    def _footprint_of(self, path):
        """Nós ocupados por um caminho (uma via ocupa as duas camadas e o entorno)."""
        new = set(path)
        for a, b2 in zip(path, path[1:]):
            if a % self.nxy == b2 % self.nxy:          # via
                p = a % self.nxy
                for layer in (0, 1):
                    new.add(layer * self.nxy + p)
                    for q in self._halo(p):
                        new.add(layer * self.nxy + q)
        return new

    def _astar(self, net, sources, target, box, pres):
        nx, nxy = self.nx, self.nxy
        static, occ, hist = self.static, self.occ, self.hist
        bx0, bx1, by0, by1 = box
        via_cost = 8.0
        best = {}
        prev = {}
        heap = []
        for s in sources:
            best[s] = 0.0
            prev[s] = None
            heapq.heappush(heap, (0.0, 0.0, s))
        expanded = 0
        while heap:
            f, gcost, u = heapq.heappop(heap)
            if gcost > best.get(u, math.inf):
                continue
            if u in target:
                path = [u]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])
                return list(reversed(path))
            expanded += 1
            if expanded > 400000:
                return None
            layer, p = divmod(u, nxy)
            iy, ix = divmod(p, nx)
            moves = []
            if ix + 1 < nx: moves.append((u + 1, layer == 1))
            if ix > 0: moves.append((u - 1, layer == 1))
            if iy + 1 < self.ny: moves.append((u + nx, layer == 0))
            if iy > 0: moves.append((u - nx, layer == 0))
            for v, wrong_dir in moves:
                sv = static[v]
                if sv != FREE and sv != net:
                    continue
                c = (2.0 if wrong_dir else 1.0) * (1.0 + hist[v]) * (1.0 + pres * occ[v])
                self._relax(u, v, gcost + c, best, prev, heap, bx0, bx1, by0, by1)
            # troca de camada (via)
            v = (1 - layer) * nxy + p
            sv = static[v]
            if sv == FREE or sv == net:
                if self._via_static_ok(p, net):
                    load = occ[p] + occ[nxy + p]
                    h = hist[p] + hist[nxy + p]
                    for q in self._halo(p):
                        load += occ[q] + occ[nxy + q]
                    c = via_cost * (1.0 + h) * (1.0 + pres * load)
                    self._relax(u, v, gcost + c, best, prev, heap, bx0, bx1, by0, by1)
        return None

    def _relax(self, u, v, gnew, best, prev, heap, bx0, bx1, by0, by1):
        if gnew < best.get(v, math.inf):
            best[v] = gnew
            prev[v] = u
            p = v % self.nxy
            iy, ix = divmod(p, self.nx)
            h = max(bx0 - ix, 0, ix - bx1) + max(by0 - iy, 0, iy - by1)
            heapq.heappush(heap, (gnew + h, gnew, v))

    # ------------------------------------------------------------- geometria
    def _emit_path(self, path, net_name):
        g, w = self.g, self.r.track_width
        run = [path[0]]

        def flush(run):
            if len(run) < 2:
                return
            layer = run[0] // self.nxy
            pts = [divmod(n % self.nxy, self.nx)[::-1] for n in run]   # (ix, iy)
            start = pts[0]
            for i in range(1, len(pts)):
                last = i == len(pts) - 1
                if not last:
                    d1 = (pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
                    d2 = (pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                    if d1 == d2:
                        continue
                self.b.tracks.append(Track(start[0] * g, start[1] * g, pts[i][0] * g, pts[i][1] * g,
                                           LAYERS[layer], net_name, w))
                start = pts[i]

        for a, b2 in zip(path, path[1:]):
            if a % self.nxy == b2 % self.nxy:
                flush(run)
                iy, ix = divmod(a % self.nxy, self.nx)
                self.b.vias.append(Via(ix * g, iy * g, net_name, self.r.via_size, self.r.via_drill))
                run = [b2]
            else:
                run.append(b2)
        flush(run)


def route(board, max_iter=40, log=print):
    rt = Router(board, log)
    if rt.planes:
        log(f"  grade {rt.nx}x{rt.ny}x2 ({rt.g} mm), {len(rt.terminals)} nets de sinal, "
            f"{len(rt.power_pads)} pads de alimentação SMD")
        failed_power = rt.fanout_power()
    else:
        log(f"  grade {rt.nx}x{rt.ny}x2 ({rt.g} mm), {len(rt.terminals)} nets de sinal, "
            f"{len(rt.stubs)} pads de alimentação ligados aos trilhos")
        failed_power = []
    if failed_power:
        log(f"  AVISO: {len(failed_power)} pads de alimentação sem fanout: {failed_power[:8]}")
    dropped = rt.route_signals(max_iter)
    board.unrouted = dropped + [f"(alim) {p}" for p in failed_power]
    return board
