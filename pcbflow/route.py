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

Desempenho: o estado da grade fica em arrays numpy e a busca A* de cada
ligação (_astar_kernel) é compilada pelo numba quando ele está instalado; sem
ele, a mesma função roda como Python puro (bem mais devagar). As duas dão o
mesmo resultado: mesma ordem de expansão e mesmo desempate.
"""

import hashlib
import heapq
import math
import os
import pickle
from pathlib import Path

import numpy as np

from .jit import COMPILED, njit, views
from .layout import Track, Via
from .progress import Progress

# inteiro dos nós na fila do A*: np.int64 fixa o tipo para o numba; em Python
# puro, int comum (aritmética com escalares numpy é lenta)
_I = np.int64 if COMPILED else int
FREE = -1
BLOCK = -2
LAYERS = ("F.Cu", "B.Cu")
# nós expandidos por busca antes de desistir: o mínimo vale para placas pequenas;
# numa grande, uma net longa precisa explorar uma região proporcional à dela
MAX_EXPAND = 400000
MAX_EXPAND_PER_NODE = 20                 # vezes a área (em nós) do retângulo da net
MAX_EXPAND_CAP = 8000000
# custo de disputa: cresce PRES_GROWTH por iteração até PRES_MAX. Sem teto ele
# chega a centenas de milhares de vezes o custo de um passo, a estimativa do A*
# deixa de orientar e as buscas que precisam contornar congestionamento estouram
# o limite; o histórico (hist) segue acumulando e cuida do longo prazo
# (adder_32bit com --row-gap 1: teto 30 -> 11 ligações pendentes, 100 -> 11,
# 300 -> 8 e o mais rápido, 1000 -> 8, sem teto -> 9)
PRES_GROWTH = 1.6
PRES_MAX = 300.0
FINAL_PRES = 1e9                         # passada final: ocupado = proibido na prática
# teto adaptativo: se as nets em conflito param de cair (menos de 3% em
# STALL_ITERS iterações), o teto do custo de disputa sobe 3×, até PRES_MAX_HARD;
# empate entre nets que trocam de lugar sem nenhuma desistir é o sintoma
STALL_ITERS = 4
PRES_MAX_HARD = 1e5
# arrancar e rerrotear (passada final): custo de disputa do caminho que pode
# cruzar outras nets, e quantas no máximo podem ser arrancadas por tentativa
RIP_PRES = (10.0, 50.0, 200.0, 1000.0, 5000.0)   # tentativas: cada uma cruza menos (ou outras) nets
RIP_MAX_VICTIMS = 30
# cadeia: uma arrancada que não volta limpa arranca outras (até RIP_DEPTH níveis,
# no máximo RIP_CHAIN_VICTIMS por nível abaixo do primeiro)
RIP_DEPTH = 5
RIP_CHAIN_VICTIMS = 8
VIA_COST = 8.0


@njit(cache=True)
def _via_ok(static, via_static, p, net, nx, ny, nxy):
    """Cabe uma via da net no ponto p (folga do furo e das trilhas vizinhas)?"""
    vs = via_static[p]
    if vs != FREE and vs != net:
        return False
    for layer in range(2):
        sv = static[layer * nxy + p]
        if sv != FREE and sv != net:
            return False
    iy = p // nx
    ix = p - iy * nx
    for k in range(4):
        jx, jy = ix, iy
        if k == 0:
            jx = ix + 1
        elif k == 1:
            jx = ix - 1
        elif k == 2:
            jy = iy + 1
        else:
            jy = iy - 1
        if jx < 0 or jx >= nx or jy < 0 or jy >= ny:
            continue
        q = jy * nx + jx
        for layer in range(2):
            sv = static[layer * nxy + q]
            if sv != FREE and sv != net and sv != BLOCK:
                return False
    return True


@njit(cache=True)
def _astar_kernel(static, via_static, occ, hist, nx, ny, net, sources, targets,
                  best, prev, seen, tmark, stamp, bx0, bx1, by0, by1, pres, max_expand):
    """A* da árvore 'sources' até qualquer nó de 'targets'. best/prev/seen/tmark
    são do tamanho da grade e reaproveitados entre buscas: um nó só vale nesta
    busca se seen (ou tmark) == stamp, o que evita limpar os arrays a cada vez.
    Devolve o caminho (array de nós) ou um array vazio."""
    nxy = nx * ny
    for t in targets:
        tmark[t] = stamp
    heap = [(0.0, 0.0, _I(0))]
    heap.pop()
    for s in sources:
        best[s] = 0.0
        prev[s] = -1
        seen[s] = stamp
        heapq.heappush(heap, (0.0, 0.0, _I(s)))
    expanded = 0
    while len(heap) > 0:
        f, gcost, u = heapq.heappop(heap)
        bu = best[u] if seen[u] == stamp else np.inf
        if gcost > bu:
            continue
        if tmark[u] == stamp:
            n = 0
            v = u
            while v != -1:
                n += 1
                v = prev[v]
            path = np.empty(n, np.int64)
            v = u
            i = n - 1
            while v != -1:
                path[i] = v
                i -= 1
                v = prev[v]
            return path
        expanded += 1
        if expanded > max_expand:
            return np.empty(0, np.int64)
        layer = u // nxy
        p = u - layer * nxy
        iy = p // nx
        ix = p - iy * nx
        # F.Cu prefere horizontal e B.Cu vertical: a direção "errada" custa o dobro
        for k in range(5):
            if k == 0:
                if ix + 1 >= nx:
                    continue
                v = u + 1
                c0 = 2.0 if layer == 1 else 1.0
            elif k == 1:
                if ix <= 0:
                    continue
                v = u - 1
                c0 = 2.0 if layer == 1 else 1.0
            elif k == 2:
                if iy + 1 >= ny:
                    continue
                v = u + nx
                c0 = 2.0 if layer == 0 else 1.0
            elif k == 3:
                if iy <= 0:
                    continue
                v = u - nx
                c0 = 2.0 if layer == 0 else 1.0
            else:
                v = (1 - layer) * nxy + p          # troca de camada (via)
            sv = static[v]
            if sv != FREE and sv != net:
                continue
            if k < 4:
                c = c0 * (1.0 + hist[v]) * (1.0 + pres * occ[v])
            else:
                if not _via_ok(static, via_static, p, net, nx, ny, nxy):
                    continue
                load = occ[p] + occ[nxy + p]
                h = hist[p] + hist[nxy + p]
                for kk in range(4):
                    jx, jy = ix, iy
                    if kk == 0:
                        jx = ix + 1
                    elif kk == 1:
                        jx = ix - 1
                    elif kk == 2:
                        jy = iy + 1
                    else:
                        jy = iy - 1
                    if jx < 0 or jx >= nx or jy < 0 or jy >= ny:
                        continue
                    q = jy * nx + jx
                    load += occ[q] + occ[nxy + q]
                c = VIA_COST * (1.0 + h) * (1.0 + pres * load)
            gnew = gcost + c
            bv = best[v] if seen[v] == stamp else np.inf
            if gnew < bv:
                best[v] = gnew
                seen[v] = stamp
                prev[v] = u
                pv = v % nxy
                vy = pv // nx
                vx = pv - vy * nx
                hh = max(bx0 - vx, 0, vx - bx1) + max(by0 - vy, 0, vy - by1)
                heapq.heappush(heap, (gnew + hh, gnew, _I(v)))
    return np.empty(0, np.int64)


def _dist_point_rect(px, py, r):
    x0, y0, x1, y1 = r
    dx = max(x0 - px, 0.0, px - x1)
    dy = max(y0 - py, 0.0, py - y1)
    return math.hypot(dx, dy)


class Router:
    def __init__(self, board, log=print, edge=True, label=""):
        """edge=False: sem a faixa proibida na borda (um macro roteia até a borda,
        onde ficam os seus pinos)."""
        self.b = board
        self.edge = edge
        self.label = label              # prefixo do progresso (ex.: "macro adder: ")
        self.r = board.rules
        self.log = log
        g = self.r.grid
        self.g = g
        self.nx = int(board.width / g) + 1
        self.ny = int(board.height / g) + 1
        self.nxy = self.nx * self.ny
        self.n = 2 * self.nxy
        self.nets = board.nets()
        # pinos de macros podem ser de nets sem nenhum pad nesta placa
        self.nets += sorted({p[0] for p in getattr(board, "pins", ())} - set(self.nets))
        self.net_id = {name: i for i, name in enumerate(self.nets)}
        self.power = {self.net_id[n] for n in (board.vdd, board.gnd) if n in self.net_id}
        self.static = np.full(self.n, FREE, np.int32)
        self.via_static = np.full(self.nxy, FREE, np.int32)
        self.terminals = {}            # net -> [set(nós) por pad]
        self.power_pads = []           # 4 camadas: pads SMD que precisam de fanout
        self.planes = getattr(board, "layers", 4) >= 4
        self.rail = {}                 # net -> nós do cobre fixo (grade de alimentação)
        self.stubs = []                # 2 camadas: (pad, net, nós do pad) a ligar ao trilho
        self._via_xy = {(int(round(v.x / self.g)), int(round(v.y / self.g))) for v in board.vias}
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
        for iy in range(self.ny if self.edge else 0):
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
        self._macro_keepouts()
        for pad in self.b.pads():
            if not pad.net:
                # pad sem ligação (pino NC de conector): obstáculo para todas as nets
                layers = (0, 1) if pad.tht else (0,)
                for ix, iy, _ in self._points_near(pad.bbox(), track_r):
                    for layer in layers:
                        self._claim(self.static, self.node(layer, ix, iy), BLOCK)
                for ix, iy, _ in self._points_near(pad.bbox(), via_r):
                    self._claim(self.via_static, iy * self.nx + ix, BLOCK)
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
            if pad.tht:
                # o furo do pad já liga as duas camadas: via ali seria um furo duplicado
                for n in term:
                    self._via_xy.add(divmod(n % self.nxy, self.nx)[::-1])
            if pad.macro:
                continue                 # já ligado por dentro do macro: só obstáculo
            if net in self.power:
                if not self.planes:
                    self.stubs.append((pad, net, term))
                elif not pad.tht:
                    self.power_pads.append((pad, net, term))
            else:
                self.terminals.setdefault(net, []).append(term)
        for net, x, y, layer in getattr(self.b, "pins", ()):
            self.add_pin(net, int(round(x / g)), int(round(y / g)), layer)

    def add_pin(self, net, ix, iy, layer):
        """Pino de macro: um ponto da grade, numa camada, que a net precisa
        alcançar (é a ponta da trilha que sai de dentro do macro)."""
        r = self.r
        net = self.net_id[net]
        for jx, jy, _ in self._points_near((ix * self.g, iy * self.g, ix * self.g, iy * self.g),
                                           r.clearance + r.track_width / 2):
            self._claim(self.static, self.node(layer, jx, jy), net)
        # o ponto do pino e os vizinhos dele na camada são a porta de entrada, mesmo
        # sobre o cobre do macro (uma via no pino bloquearia o vizinho de fora),
        # mas só onde o cobre de macro ali é da própria net
        owner = getattr(self, "macro_owner", None)
        self.static[self.node(layer, ix, iy)] = net
        for jx, jy in ((ix + 1, iy), (ix - 1, iy), (ix, iy + 1), (ix, iy - 1)):
            if not (0 <= jx < self.nx and 0 <= jy < self.ny):
                continue
            k = self.node(layer, jx, jy)
            if self.static[k] == BLOCK and owner is not None and owner[k] == net:
                self.static[k] = net
        self.terminals.setdefault(net, []).append({self.node(layer, ix, iy)})

    def _fixed_copper(self):
        """Trilhas e vias que já existem na placa (a grade de alimentação da placa
        de 2 camadas) viram obstáculo para as outras nets e alvo para a própria."""
        r = self.r
        # cobre de macros já roteados (fluxo hierárquico): obstáculo até para a
        # própria net, que só entra pelo pino (add_pin); andar por cima dele
        # duplicaria trilhas. O espaço livre de dentro do macro continua valendo.
        macro = bool(getattr(self.b, "macro_rects", None))
        # de quem é o cobre de macro em cada ponto (BLOCK: de mais de uma net):
        # add_pin só abre o entorno do pino onde o cobre é da própria net
        self.macro_owner = np.full(self.n, FREE, np.int32) if macro else None
        for t in self.b.tracks:
            net = self.net_id[t.net]
            layer = LAYERS.index(t.layer)
            rect = (min(t.x1, t.x2), min(t.y1, t.y2), max(t.x1, t.x2), max(t.y1, t.y2))
            nodes = self.rail.setdefault(net, set())
            for ix, iy, d in self._points_near(rect, t.width / 2 + r.clearance + r.track_width / 2):
                self._claim(self.static, self.node(layer, ix, iy), BLOCK if macro else net)
                if macro:
                    self._claim(self.macro_owner, self.node(layer, ix, iy), net)
                if d <= t.width / 2 + 1e-9:
                    nodes.add(self.node(layer, ix, iy))
            for ix, iy, d in self._points_near(rect, t.width / 2 + r.clearance + r.via_size / 2):
                self._claim(self.via_static, iy * self.nx + ix, BLOCK if macro else net)
        for v in self.b.vias:
            net = self.net_id[v.net]
            rect = (v.x, v.y, v.x, v.y)
            nodes = self.rail.setdefault(net, set())
            for ix, iy, d in self._points_near(rect, v.size / 2 + r.clearance + r.track_width / 2):
                for layer in (0, 1):
                    self._claim(self.static, self.node(layer, ix, iy), BLOCK if macro else net)
                    if macro:
                        self._claim(self.macro_owner, self.node(layer, ix, iy), net)
                    if d <= v.size / 2 + 1e-9:
                        nodes.add(self.node(layer, ix, iy))
            for ix, iy, d in self._points_near(rect, v.size + r.clearance):
                self._claim(self.via_static, iy * self.nx + ix, BLOCK if macro else net)

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

    def _macro_keepouts(self):
        """Com board.macro_keepout, o espaço livre dentro de cada macro também é
        proibido: trilha nenhuma de fora com o centro no retângulo dele, nem via
        cujo cobre o alcance. A rota só chega ao pino, que fica na borda: o
        add_pin, que roda depois, reabre o ponto dele."""
        if not getattr(self.b, "macro_keepout", False):
            return
        g = self.g
        for x0, y0, x1, y1 in getattr(self.b, "macro_rects", ()):
            ix0, ix1 = max(0, math.ceil(x0 / g - 1e-9)), min(self.nx - 1, math.floor(x1 / g + 1e-9))
            iy0, iy1 = max(0, math.ceil(y0 / g - 1e-9)), min(self.ny - 1, math.floor(y1 / g + 1e-9))
            for iy in range(iy0, iy1 + 1):
                for ix in range(ix0, ix1 + 1):
                    for layer in (0, 1):
                        i = self.node(layer, ix, iy)
                        if self.static[i] == FREE:
                            self.static[i] = BLOCK
            for ix, iy, _ in self._points_near((x0, y0, x1, y1), self.r.via_size / 2):
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
                if (ix, iy) not in self._via_xy:
                    self._via_xy.add((ix, iy))
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
    def route_signals(self, max_iter=40, checkpoint=None, key=None):
        """checkpoint: arquivo onde o estado é gravado ao fim de cada iteração
        (e de onde ele é retomado, se for desta mesma placa: key)."""
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
        self.occ = np.zeros(self.n, np.int32)
        self.hist = np.zeros(self.n, np.float64)
        # memória da busca, reaproveitada entre as chamadas (ver _astar_kernel)
        self._best = np.zeros(self.n, np.float64)
        self._prev = np.zeros(self.n, np.int64)
        self._seen = np.zeros(self.n, np.int32)
        self._tmark = np.zeros(self.n, np.int32)
        self._stamp = 0
        # o que a busca recebe: os próprios arrays (numba) ou, em Python puro,
        # memoryviews deles, cuja leitura elemento a elemento é bem mais rápida
        # (mesma memória: as somas vetorizadas em occ/hist continuam valendo)
        grid = (self.static, self.via_static, self.occ, self.hist,
                self._best, self._prev, self._seen, self._tmark)
        self._grid = views(grid)
        self.usage = {n: set() for n in nets}
        self.paths = {n: [] for n in nets}
        self.ok = set()
        pres = 0.5
        todo = list(nets)
        conflicted = set()
        failed = []
        prev = ""
        start = 0
        cap, best, stall = PRES_MAX, None, 0
        # melhor iteração vista (menos nets em conflito): se a negociação piora no
        # fim, a passada final parte dela e não da última
        snap = None
        state = _load_checkpoint(checkpoint, key)
        if state is not None:
            # retomada: os caminhos voltam (e com eles a ocupação), o histórico de
            # disputa também; a próxima iteração continua de onde a gravada parou
            for k, ps in state["paths"].items():
                if k in self.paths:
                    self.paths[k] = [p.tolist() for p in ps]
                    used = set()
                    for p in self.paths[k]:
                        used |= self._footprint_of(p)
                    self.usage[k] = used
                    self._occ_add(used, 1)
            self.hist[state["hist_idx"]] = state["hist_val"]
            self.ok = set(state["ok"]) & set(nets)
            pres, todo, prev, start = state["pres"], [k for k in state["todo"] if k in self.jobs], \
                state["prev"], state["it"] + 1
            cap, best, stall = state.get("cap", PRES_MAX), state.get("best"), state.get("stall", 0)
            if state.get("snap"):
                n_snap, it_snap, ps_snap, ok_snap = state["snap"]
                snap = (n_snap, it_snap, {k: [p.tolist() for p in ps] for k, ps in ps_snap.items()},
                        set(ok_snap))
            self.log(f"  retomado do ponto de controle: {start} iteração(ões) já feita(s), "
                     f"{len(todo)} net(s) a refazer")
        for it in range(start, max_iter):
            if not todo and it > 0:          # retomado de um roteamento que já tinha fechado
                break
            failed = []
            # a 1ª iteração roteia todas as nets; as seguintes, só as em conflito.
            # As nets vão da menor para a maior: o progresso pesa cada uma pelo
            # tamanho (contar nets subestimaria o tempo das últimas)
            w = [bbox_size(net) + 4 for net in todo]
            total, acc = sum(w), 0
            with Progress(f"{self.label}roteamento: iteração {it + 1} (máx. {max_iter})", total=total,
                          show_count=False) as pg:
                for k, net in enumerate(todo):
                    self._rip(net)
                    if not self._route_net(net, pres):
                        failed.append(net)
                    acc += w[k]
                    pg.update(acc, f"{k + 1}/{len(todo)} nets" + (f" · {prev}" if prev else ""))
            over = np.flatnonzero(self.occ > 1)
            self.hist[over] += 0.4
            over_set = set(over.tolist())
            conflicted = {n for n in nets if self.usage[n] & over_set}
            self.log(f"  iteração {it + 1:2d}: nós em conflito={len(over):5d}  "
                     f"nets em conflito={len(conflicted):4d}  falhas={len(failed)}")
            if not len(over) and not failed:
                todo = []
                _save_checkpoint(checkpoint, key, it, pres, self.hist, self.paths, todo, self.ok, prev,
                                 cap=cap, best=best, stall=stall)
                break
            prev = f"anterior: {len(conflicted)} nets em conflito"
            todo = sorted(conflicted | set(failed), key=bbox_size)
            n_conf = len(conflicted) + len(failed)
            if snap is None or n_conf <= snap[0]:
                snap = (n_conf, it + 1, {k: list(ps) for k, ps in self.paths.items() if ps}, set(self.ok))
            if best is None or n_conf < best * 0.97:
                best, stall = n_conf, 0
            elif cap > PRES_MAX and n_conf > best * 1.5:
                # o teto alto fez as nets trocarem de lugar sem parar: volta um passo
                cap, stall = max(PRES_MAX, cap / 3), 0
                self.log(f"  negociação divergindo: teto do custo de disputa volta para {cap:g}")
            else:
                stall += 1
                if stall >= STALL_ITERS and cap < PRES_MAX_HARD and n_conf <= best * 1.25:
                    cap, stall = min(cap * 3, PRES_MAX_HARD), 0
                    self.log(f"  negociação estacionada: teto do custo de disputa sobe para {cap:g}")
            pres = min(pres * PRES_GROWTH, cap)
            _save_checkpoint(checkpoint, key, it, pres, self.hist, self.paths, todo, self.ok, prev,
                             cap=cap, best=best, stall=stall, snap=snap and (
                                 snap[0], snap[1],
                                 {k: [np.asarray(p, np.int64) for p in ps] for k, ps in snap[2].items()},
                                 list(snap[3])))
        if todo and snap is not None and snap[0] < len(conflicted) + len(failed):
            self.log(f"  a última iteração ({len(conflicted) + len(failed)} nets em conflito) é pior que a "
                     f"{snap[1]} ({snap[0]}): a passada final parte da {snap[1]}")
            for n in nets:
                self._rip(n)
            for k, ps in snap[2].items():
                self.paths[k] = list(ps)
                used = set()
                for p in ps:
                    used |= self._footprint_of(p)
                self.usage[k] = used
                self._occ_add(used, 1)
            self.ok = set(snap[3]) & set(nets)
        # nets que continuam em conflito são descartadas (ficam no ratsnest)
        dropped = set(n for n in nets if n not in self.ok)
        pg = Progress(f"{self.label}roteamento: descartando nets que seguem em conflito", tick=True)
        with pg:
            self._drop_conflicts(nets, dropped, bbox_size, pg)
        if dropped:
            self._final_pass(dropped, bbox_size)
        for key in nets:
            for path in self.paths[key]:
                self._emit_path(path, self.nets[self.jobs[key][0]])
        return sorted(self._job_name(k) for k in dropped)

    def _final_pass(self, dropped, bbox_size):
        """Uma última tentativa para cada net descartada, contra a placa já roteada:
        o que está ocupado vira obstáculo (custo de disputa enorme) e o limite de
        busca é o máximo. Um caminho que ainda assim cruze outra net é recusado.
        O que sobrar é classificado: bloqueio físico (sem caminho nem com a placa
        vazia) ou falta de espaço."""
        recovered = []
        with Progress(f"{self.label}roteamento: passada final das descartadas", total=len(dropped)) as pg:
            for k, key in enumerate(sorted(dropped, key=bbox_size)):
                pg.update(k)
                if self._route_net(key, FINAL_PRES, relax=False, wide=True):
                    if any(self.occ[i] > 1 for i in self.usage[key]):
                        self._rip(key)
                    else:
                        recovered.append(key)
        for key in recovered:
            dropped.discard(key)
        ripped = self._ripup_reroute(dropped, bbox_size) if dropped else 0
        blocked = []
        for key in sorted(dropped, key=bbox_size):
            # com custo de disputa zero a ocupação não importa: é a placa vazia
            if self._route_net(key, 0.0, relax=False, wide=True):
                self._rip(key)
            else:
                blocked.append(key)
        self.log(f"  passada final: {len(recovered) + ripped} de {len(recovered) + ripped + len(dropped)} "
                 f"net(s) descartada(s) recuperada(s) ({ripped} arrancando e rerroteando outras)" + (f"; sobram {len(dropped)}: {len(blocked)} por bloqueio físico (sem caminho "
                                     f"nem com a placa vazia), {len(dropped) - len(blocked)} por falta de espaço"
                                     if dropped else ""))
        self.blocked = {self._job_name(k) for k in blocked}

    def _ripup_reroute(self, dropped, bbox_size, rounds=3):
        """Arrancar e rerrotear: para cada net que segue sem caminho, acha um
        caminho que pode cruzar outras (custo de disputa moderado), arranca as que
        ele cruza (até RIP_MAX_VICTIMS), coloca a net e rerroteia as arrancadas sem
        cruzar ninguém. Se alguma não volta, tudo é desfeito: só fica a troca que
        diminui as pendências. Devolve quantas nets foram recuperadas."""
        done = 0
        with Progress(f"{self.label}roteamento: arrancando e rerroteando", tick=True) as pg:
            for rnd in range(rounds):
                progress = False
                for key in sorted(list(dropped), key=bbox_size):
                    pg.update(info=f"rodada {rnd + 1}: {done} recuperada(s), {len(dropped)} pendente(s)")
                    for rip_pres in RIP_PRES:
                        if self._try_ripup(key, rip_pres, dropped, bbox_size):
                            dropped.discard(key)
                            done += 1
                            progress = True
                            break
                if not progress or not dropped:
                    break
        return done

    def _try_ripup(self, key, rip_pres, dropped, bbox_size):
        """Uma tentativa de arrancar e rerrotear para a net 'key' (ver _ripup_reroute);
        True se ela ficou roteada e todas as arrancadas voltaram sem cruzar ninguém.
        Uma arrancada que não volta limpa pode arrancar outras por sua vez, em
        cadeia de até RIP_DEPTH níveis; se a cadeia falha, tudo volta como estava."""
        saved, placed = {}, set()
        if self._ripup_chain(key, rip_pres, dropped, bbox_size, RIP_DEPTH, saved, placed):
            return True
        for n in placed | set(saved) | {key}:
            if self.usage.get(n):
                self._rip(n)
        for v, (ps, used) in saved.items():
            self.paths[v], self.usage[v] = ps, used
            self._occ_add(used, 1)
            self.ok.add(v)
        return False

    def _ripup_chain(self, key, rip_pres, dropped, bbox_size, depth, saved, placed):
        if self._route_net(key, FINAL_PRES, relax=False, wide=True):
            if not any(self.occ[i] > 1 for i in self.usage[key]):
                placed.add(key)
                return True
            self._rip(key)
        if depth == 0 or not self._route_net(key, rip_pres, relax=False, wide=True):
            return False
        mine = self.usage[key]
        victims = [n for n, used in self.usage.items()
                   if n != key and n not in dropped and used and not used.isdisjoint(mine)]
        limit = RIP_MAX_VICTIMS if depth == RIP_DEPTH else RIP_CHAIN_VICTIMS
        if len(victims) > limit or any(v in placed for v in victims):
            self._rip(key)
            return False
        for v in victims:
            saved.setdefault(v, (self.paths[v], self.usage[v]))
            self._rip(v)
        placed.add(key)
        for v in sorted(victims, key=bbox_size, reverse=True):   # as maiores primeiro
            if not self._ripup_chain(v, rip_pres, dropped, bbox_size, depth - 1, saved, placed):
                return False
        return not any(self.occ[i] > 1 for i in self.usage[key])

    def _drop_conflicts(self, nets, dropped, bbox_size, pg):
        while True:
            over = np.flatnonzero(self.occ > 1)
            pg.update(info=f"{len(over)} nós em conflito, {len(dropped)} nets descartadas")
            if not len(over):
                break
            score = {}
            over_set = set(over.tolist())
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

    def _occ_add(self, nodes, delta):
        if nodes:
            self.occ[np.fromiter(nodes, np.int64, len(nodes))] += delta

    def _rip(self, net):
        self._occ_add(self.usage[net], -1)
        self.usage[net] = set()
        self.paths[net] = []
        self.ok.discard(net)

    def _search(self, net, sources, target, box, pres, relax, wide=False):
        """A* com nova tentativa: se a busca não acha caminho (em geral por estourar
        o limite contornando congestionamento), tenta de novo sem custo de
        disputa e com o limite máximo. A net ganha um caminho, talvez sobreposto,
        e entra na negociação; só fica sem caminho o que é bloqueio físico."""
        path = self._astar(net, sources, target, box, pres, wide=wide)
        if path is None and relax and pres > 0:
            path = self._astar(net, sources, target, box, 0.0, wide=True)
        return path

    def _route_net(self, key, pres, relax=True, wide=False):
        net, terms = self.jobs[key]
        if terms[1] is None:                 # pad de alimentação -> trilho
            target, box = self.rail_target[net]
            if not terms[0].isdisjoint(target):
                self.ok.add(key)
                return True
            path = self._search(net, terms[0], target, box, pres, relax, wide)
            if path is None:
                return False
            self.usage[key] = self._footprint_of(path)
            self._occ_add(self.usage[key], 1)
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
            path = self._search(net, tree, target, box, pres, relax, wide)
            if path is None:
                self._occ_add(used, -1)
                return False
            paths.append(path)
            tree.update(path)
            new = self._footprint_of(path)
            self._occ_add(new - used, 1)
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

    def _astar(self, net, sources, target, box, pres, wide=False):
        """Caminho de menor custo da árvore 'sources' até um nó de 'target' (ou None).
        wide: usa o limite de expansão máximo (nova tentativa, passada final)."""
        self._stamp += 1
        bx0, bx1, by0, by1 = box
        static, via_static, occ, hist, best, prev, seen, tmark = self._grid
        # limite de expansão pela região da net: retângulo das origens e dos alvos
        xs = [n % self.nxy % self.nx for n in sources]
        ys = [n % self.nxy // self.nx for n in sources]
        area = (max(max(xs), bx1) - min(min(xs), bx0) + 1) * (max(max(ys), by1) - min(min(ys), by0) + 1)
        limit = int(min(MAX_EXPAND_CAP, max(MAX_EXPAND, MAX_EXPAND_PER_NODE * area)))
        if wide:
            limit = MAX_EXPAND_CAP
        if COMPILED:
            sources = np.fromiter(sources, np.int64, len(sources))
            target = np.fromiter(target, np.int64, len(target))
        path = _astar_kernel(static, via_static, occ, hist, self.nx, self.ny, net, sources, target,
                             best, prev, seen, tmark, self._stamp, bx0, bx1, by0, by1, float(pres), limit)
        return path.tolist() if len(path) else None

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
                # já há uma via da net ali (de um macro ou de outro trecho): não duplica o furo
                if (ix, iy) not in self._via_xy:
                    self._via_xy.add((ix, iy))
                    self.b.vias.append(Via(ix * g, iy * g, net_name, self.r.via_size, self.r.via_drill))
                run = [b2]
            else:
                run.append(b2)
        flush(run)


# versão do formato do ponto de controle: sobe quando o estado gravado muda de
# significado. Ajustes no roteador que não mudam o estado (passada final, teto
# do custo de disputa) não invalidam um roteamento em andamento
CHECKPOINT_FORMAT = "1"


def board_key(board):
    """Impressão digital da placa a rotear (componentes, cobre já existente,
    pinos, áreas) e do formato do estado: um ponto de controle só vale para ela."""
    h = hashlib.sha256()
    h.update(CHECKPOINT_FORMAT.encode())
    h.update(repr((board.width, board.height, getattr(board, "layers", 4))).encode())
    for f in board.footprints:
        h.update(repr((f.lib_name, round(f.x, 4), round(f.y, 4),
                       [(p.num, p.net, p.macro) for p in f.pads])).encode())
    for t in board.tracks:
        h.update(repr((t.x1, t.y1, t.x2, t.y2, t.layer, t.net)).encode())
    for v in board.vias:
        h.update(repr((v.x, v.y, v.net)).encode())
    h.update(repr((getattr(board, "pins", []), getattr(board, "macro_rects", []),
                   getattr(board, "macro_keepout", False),
                   [(k.rect, k.route, k.layers) for k in getattr(board, "keepouts", [])])).encode())
    return h.hexdigest()


def _load_checkpoint(path, key):
    if not path or not key or not Path(path).is_file():
        return None
    try:
        with open(path, "rb") as f:
            state = pickle.load(f)
    except Exception:
        return None
    return state if state.get("key") == key else None


def _save_checkpoint(path, key, it, pres, hist, paths, todo, ok, prev, **extra):
    """Grava o estado ao fim de uma iteração (atômico: uma rodada interrompida no
    meio da gravação não deixa um arquivo pela metade)."""
    if not path or not key:
        return
    idx = np.flatnonzero(hist)
    state = {"key": key, "it": it, "pres": pres, "hist_idx": idx, "hist_val": hist[idx],
             "paths": {k: [np.asarray(p, np.int64) for p in ps] for k, ps in paths.items() if ps},
             "todo": list(todo), "ok": list(ok), "prev": prev, **extra}
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def route(board, max_iter=40, log=print, checkpoint=None):
    """checkpoint: arquivo do ponto de controle (retoma o roteamento desta mesma
    placa de onde parou; None: sem ponto de controle)."""
    log("  busca A*: " + ("compilada (numba)" if COMPILED else
                          "Python puro (instale o numba para rotear dezenas de vezes mais rápido)"))
    key = board_key(board) if checkpoint else None
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
    dropped = rt.route_signals(max_iter, checkpoint, key)
    board.unrouted = dropped + [f"(alim) {p}" for p in failed_power]
    board.unrouted_blocked = sorted(getattr(rt, "blocked", ()))     # sem caminho nem com a placa vazia
    removed = remove_useless_vias(board)
    if removed:
        log(f"  {removed} via(s) sem cobre na outra camada removida(s)")
    return board


def remove_useless_vias(board):
    """Tira as vias de sinal com cobre numa camada só: as trilhas dos dois lados
    já se tocam nessa camada (aparece quando uma rota chega a um pino de macro
    pela camada errada e a de fora sai pela mesma). As de VDD/GND ficam: ligam
    ao plano interno, que não é trilha."""
    power = {board.vdd, board.gnd}
    eps = 1e-6
    by_net = {}
    for t in board.tracks:
        by_net.setdefault(t.net, []).append(t)
    pads = {}
    for f in board.footprints:
        for p in f.pads:
            if p.net:
                pads.setdefault(p.net, []).append(p)

    def touches(v, layer):
        for t in by_net.get(v.net, ()):
            if t.layer == layer and min(t.x1, t.x2) - eps <= v.x <= max(t.x1, t.x2) + eps                     and min(t.y1, t.y2) - eps <= v.y <= max(t.y1, t.y2) + eps:
                return True
        return any(layer in p.layers and p.dist(v.x, v.y) <= eps for p in pads.get(v.net, ()))

    keep = [v for v in board.vias
            if v.net in power or (touches(v, "F.Cu") and touches(v, "B.Cu"))]
    removed = len(board.vias) - len(keep)
    board.vias = keep
    return removed
